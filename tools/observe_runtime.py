"""Windows process/module metadata and read-only memory APIs for session discovery."""

import ctypes as C
from ctypes import wintypes as W


PROCESS_ACCESS = 0x0010 | 0x0400
MEM_COMMIT = 0x1000
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
