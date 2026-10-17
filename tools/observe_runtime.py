"""Bounded, read-only observation of candidate game vtables on Windows x64.

Opens the process with PROCESS_VM_READ | PROCESS_QUERY_INFORMATION only.
Candidates are byte patterns, never established live objects or loot targets.
"""

import argparse
import ctypes as C
from ctypes import wintypes as W
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import struct
import time


CLASSES = ("BodyContainer", "Container", "ContainerItem", "GameDI_PH", "TriggerController")
PROCESS_ACCESS = 0x0010 | 0x0400
MEM_COMMIT, MEM_PRIVATE = 0x1000, 0x20000
WRITABLE = {0x04, 0x08, 0x40, 0x80}
INVALID_HANDLE = C.c_void_p(-1).value


class MODULEENTRY32W(C.Structure):
    _fields_ = [("dwSize", W.DWORD), ("th32ModuleID", W.DWORD),
                ("th32ProcessID", W.DWORD), ("GlblcntUsage", W.DWORD),
                ("ProccntUsage", W.DWORD), ("modBaseAddr", C.c_void_p),
                ("modBaseSize", W.DWORD), ("hModule", W.HMODULE),
                ("szModule", W.WCHAR * 256), ("szExePath", W.WCHAR * 260)]


class MEMORY_BASIC_INFORMATION(C.Structure):
    _fields_ = [("BaseAddress", C.c_void_p), ("AllocationBase", C.c_void_p),
                ("AllocationProtect", W.DWORD), ("PartitionId", W.WORD),
                ("RegionSize", C.c_size_t), ("State", W.DWORD),
                ("Protect", W.DWORD), ("Type", W.DWORD)]


class SYSTEM_INFO(C.Structure):
    _fields_ = [("wProcessorArchitecture", W.WORD), ("wReserved", W.WORD),
                ("dwPageSize", W.DWORD), ("lpMinimumApplicationAddress", C.c_void_p),
                ("lpMaximumApplicationAddress", C.c_void_p),
                ("dwActiveProcessorMask", C.c_size_t), ("dwNumberOfProcessors", W.DWORD),
                ("dwProcessorType", W.DWORD), ("dwAllocationGranularity", W.DWORD),
                ("wProcessorLevel", W.WORD), ("wProcessorRevision", W.WORD)]


def windows_api():
    api = C.WinDLL("kernel32", use_last_error=True)
    signatures = {
        "OpenProcess": ([W.DWORD, W.BOOL, W.DWORD], W.HANDLE),
        "CloseHandle": ([W.HANDLE], W.BOOL),
        "CreateToolhelp32Snapshot": ([W.DWORD, W.DWORD], W.HANDLE),
        "Module32FirstW": ([W.HANDLE, C.POINTER(MODULEENTRY32W)], W.BOOL),
        "Module32NextW": ([W.HANDLE, C.POINTER(MODULEENTRY32W)], W.BOOL),
        "VirtualQueryEx": ([W.HANDLE, C.c_void_p, C.POINTER(MEMORY_BASIC_INFORMATION), C.c_size_t], C.c_size_t),
        "ReadProcessMemory": ([W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)], W.BOOL),
        "GetSystemInfo": ([C.POINTER(SYSTEM_INFO)], None),
        "GetExitCodeProcess": ([W.HANDLE, C.POINTER(W.DWORD)], W.BOOL),
    }
    for name, (args, result) in signatures.items():
        getattr(api, name).argtypes = args
        getattr(api, name).restype = result
    return api


def modules(api, pid):
    snapshot = api.CreateToolhelp32Snapshot(0x08 | 0x10, pid)
    if snapshot == INVALID_HANDLE:
        raise C.WinError(C.get_last_error())
    result = []
    try:
        entry = MODULEENTRY32W()
        entry.dwSize = C.sizeof(entry)
        if not api.Module32FirstW(snapshot, C.byref(entry)):
            raise C.WinError(C.get_last_error())
        while True:
            result.append({"name": entry.szModule, "path": entry.szExePath,
                           "base": hex(entry.modBaseAddr), "size": entry.modBaseSize})
            if not api.Module32NextW(snapshot, C.byref(entry)):
                if C.get_last_error() != 18:  # ERROR_NO_MORE_FILES
                    raise C.WinError(C.get_last_error())
                break
    finally:
        api.CloseHandle(snapshot)
    return result


def observe(args):
    started = time.monotonic()
    deadline = started + args.seconds
    api = windows_api()
    loaded = modules(api, args.pid)
    if not any(m["name"].lower() == "dyinglightgame_thebeast_x64_rwdi.exe" for m in loaded):
        raise RuntimeError("PID does not contain the expected The Beast executable")
    table_data = json.loads(args.vtables.read_text(encoding="utf-8-sig"))
    expected_dll = str(Path(table_data["file"]).resolve()).lower()
    game = next(m for m in loaded if str(Path(m["path"]).resolve()).lower() == expected_dll)
    relevant_modules = [m for m in loaded if "gamedll" in m["name"].lower() or "engine" in m["name"].lower()]
    for module in relevant_modules:
        with open(module["path"], "rb") as stream:
            module["disk_sha256"] = hashlib.file_digest(stream, "sha256").hexdigest()
    targets = {}
    for name in getattr(args, 'classes', CLASSES):
        primary = [v for v in table_data["vtables"] if v["class"] == name and v["subobject_offset"] == 0]
        if len(primary) != 1:
            raise ValueError(f"Expected one primary vtable for {name}, found {len(primary)}")
        rva = int(primary[0]["vtable_rva"], 0)
        if not 0 <= rva < game["size"]:
            raise ValueError(f"Vtable outside loaded module: {name}")
        address = int(game["base"], 0) + rva
        targets[name] = {"vtable_rva": hex(rva), "vtable_address": hex(address),
                         "pattern": struct.pack("<Q", address), "candidates": [], "seen": set(), "cap_reached": False}
    handle = api.OpenProcess(PROCESS_ACCESS, False, args.pid)
    if not handle:
        raise C.WinError(C.get_last_error())
    stats = {"regions_queried": 0, "eligible_regions": 0, "eligible_bytes_encountered": 0,
             "regions_skipped_by_size": 0, "bytes_skipped_by_size": 0,
             "bytes_requested": 0, "bytes_read": 0, "scan_bytes_read": 0,
             "read_calls": 0, "failed_or_partial_reads": 0, "confirmation_mismatches": 0}

    def read(address, size):
        size = min(size, args.max_bytes - stats["bytes_requested"])
        if size <= 0 or time.monotonic() >= deadline:
            return b""
        buffer = C.create_string_buffer(size)
        count = C.c_size_t()
        ok = api.ReadProcessMemory(handle, address, buffer, size, C.byref(count))
        stats["bytes_requested"] += size
        stats["bytes_read"] += count.value
        stats["read_calls"] += 1
        if not ok or count.value != size:
            stats["failed_or_partial_reads"] += 1
        return buffer.raw[:count.value]

    system = SYSTEM_INFO()
    api.GetSystemInfo(C.byref(system))
    global_end = system.lpMaximumApplicationAddress + 1
    end = args.end_address if args.end_address is not None else global_end
    address = args.start_address if args.start_address is not None else system.lpMinimumApplicationAddress
    if not system.lpMinimumApplicationAddress <= address < end <= global_end:
        api.CloseHandle(handle)
        raise ValueError("requested range outside application address space or empty")
    start_address = address
    reason = "address_range_complete"
    try:
        while address < end:
            if time.monotonic() >= deadline:
                reason = "time_limit"
                break
            if stats["bytes_requested"] >= args.max_bytes:
                reason = "byte_limit"
                break
            if all(target["cap_reached"] for target in targets.values()):
                reason = "all_class_caps_reached"
                break
            region = MEMORY_BASIC_INFORMATION()
            if not api.VirtualQueryEx(handle, address, C.byref(region), C.sizeof(region)):
                reason = "virtual_query_failed"
                stats["virtual_query_error"] = C.get_last_error()
                break
            stats["regions_queried"] += 1
            base = region.BaseAddress or 0
            next_address = min(base + region.RegionSize, end)
            if next_address <= address:
                reason = "nonadvancing_region"
                break
            size_limit = getattr(args, 'max_region_bytes', None)
            eligible = (region.State == MEM_COMMIT and region.Type == MEM_PRIVATE
                        and (region.Protect & 0xff) in WRITABLE and not region.Protect & 0x100)
            if eligible and size_limit is not None and region.RegionSize > size_limit:
                stats['regions_skipped_by_size'] += 1
                stats['bytes_skipped_by_size'] += min(base + region.RegionSize, end) - max(base, address)
                eligible = False
            if eligible:
                stats["eligible_regions"] += 1
                cursor, carry = max(base, address), b""
                stats["eligible_bytes_encountered"] += next_address - cursor
                while cursor < next_address:
                    if time.monotonic() >= deadline or stats["bytes_requested"] >= args.max_bytes or all(target["cap_reached"] for target in targets.values()):
                        break
                    size = min(args.chunk_bytes, next_address - cursor, args.max_bytes - stats["bytes_requested"])
                    raw = read(cursor, size)
                    stats["scan_bytes_read"] += len(raw)
                    block = carry + raw
                    block_address = cursor - len(carry)
                    for target in targets.values():
                        if target["cap_reached"]:
                            continue
                        offset = block.find(target["pattern"])
                        while offset >= 0:
                            candidate = block_address + offset
                            if candidate % 8 == 0 and candidate not in target["seen"]:
                                target["seen"].add(candidate)
                                confirmed = read(candidate, 256)
                                if len(confirmed) >= 8 and confirmed[:8] == target["pattern"]:
                                    target["candidates"].append({"address": hex(candidate),
                                        "vtable_reread_confirmed": True, "prefix_bytes": len(confirmed),
                                        "prefix_hex": confirmed.hex(), "region_base": hex(base),
                                        "region_size": region.RegionSize, "region_protection": hex(region.Protect)})
                                    if len(target["candidates"]) >= args.max_per_class:
                                        target["cap_reached"] = True
                                        break
                                else:
                                    stats["confirmation_mismatches"] += 1
                            offset = block.find(target["pattern"], offset + 1)
                    carry = raw[-7:] if len(raw) == size else b""
                    cursor += size
                if cursor < next_address:
                    reason = ("time_limit" if time.monotonic() >= deadline else
                              "byte_limit" if stats["bytes_requested"] >= args.max_bytes else "all_class_caps_reached")
                    address = cursor
                    break
            address = next_address
        exit_code = W.DWORD()
        exit_query_ok = bool(api.GetExitCodeProcess(handle, C.byref(exit_code)))
    finally:
        api.CloseHandle(handle)
    for target in targets.values():
        del target["pattern"], target["seen"]
    return {"pid": args.pid, "observed_at_utc": datetime.now(timezone.utc).isoformat(),
            "access": {"mask": hex(PROCESS_ACCESS), "rights": ["PROCESS_VM_READ", "PROCESS_QUERY_INFORMATION"], "read_only": True},
            "modules": relevant_modules, "all_module_count": len(loaded),
            "vtables_source": str(args.vtables.resolve()),
            "limits": {"seconds": args.seconds, "max_bytes_requested": args.max_bytes,
                       "chunk_bytes": args.chunk_bytes, "max_candidates_per_class": args.max_per_class,
                       "max_region_bytes_heuristic": getattr(args, 'max_region_bytes', None),
                       "eligible_regions": "MEM_PRIVATE | MEM_COMMIT; READWRITE, WRITECOPY, EXECUTE_READWRITE or EXECUTE_WRITECOPY; no PAGE_GUARD"},
            "scan": {**stats, "elapsed_seconds": round(time.monotonic() - started, 3),
                     "stop_reason": reason,
                     "address_range_complete": reason == "address_range_complete",
                     "address_space_complete": reason == "address_range_complete" and start_address == system.lpMinimumApplicationAddress and end == global_end,
                     "start_address": hex(start_address),
                     "end_address_exclusive": hex(end),
                     "full_application_address_space_scanned": reason == "address_range_complete" and start_address == system.lpMinimumApplicationAddress and end == global_end,
                     "next_scan_address": hex(address), "maximum_application_address": hex(system.lpMaximumApplicationAddress),
                     "process_exit_code": exit_code.value if exit_query_ok else None},
            "targets": targets,
            "interpretation": "Candidates confirm only an aligned primary-vtable byte pattern on a reread. They are not validated objects, collectible targets, player positions, or evidence of a 3 metre radius.",
            "caveats": ["The process is not paused; allocations and bytes may change during observation.",
                        "An optional maximum region size is a heuristic: skipped large regions may contain valid objects.",
                        "Candidate caps can truncate each class even if address-space traversal completes.",
                        "Unscanned region types/protections, failed reads and imposed limits can hide instances.",
                        "Disk DLL hashes identify disk files at observation time, not every mapped process byte."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--vtables", type=Path, default=Path("evidence/native-vtables.json"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seconds", type=float, default=45)
    parser.add_argument("--max-bytes", type=int, default=4 * 1024**3)
    parser.add_argument("--chunk-bytes", type=int, default=4 * 1024**2)
    parser.add_argument("--max-per-class", type=int, default=128)
    parser.add_argument("--classes", nargs='+', choices=CLASSES, default=list(CLASSES),
                        help="Only scan the requested primary vtable patterns")
    parser.add_argument("--max-region-bytes", type=int, default=None,
                        help="Optional heuristic: skip larger committed regions; can miss objects")
    parser.add_argument("--start-address", type=lambda value: int(value, 0), default=None)
    parser.add_argument("--end-address", type=lambda value: int(value, 0), default=None,
                        help="exclusive address bound")
    args = parser.parse_args()
    if C.sizeof(C.c_void_p) != 8:
        parser.error("64-bit Python required")
    if not (0 < args.seconds <= 45 and 0 < args.max_bytes <= 6 * 1024**3 and 0 < args.chunk_bytes <= 4 * 1024**2 and 0 < args.max_per_class <= 128):
        parser.error("bounds must be positive and cannot exceed 45 s, 6 GiB, 4 MiB or 128 candidates")
    if args.max_region_bytes is not None and args.max_region_bytes <= 0:
        parser.error("maximum region bytes must be positive")
    report = observe(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "scan": report["scan"],
                      "counts": {name: len(target["candidates"]) for name, target in report["targets"].items()}}, indent=2))


if __name__ == "__main__":
    main()
