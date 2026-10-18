# Better AutoLoot — Dying Light: The Beast

Automatically loot corpses, crafting components, bags and supported containers within **2 metres**, with a **100 ms** target interval. No aiming or button presses required.

Once installed, AutoLoot detects the game every **10 seconds** and starts when a saved game is ready. Looting stops when the game closes. The background watcher also starts at Windows sign-in, without a console window.

## Requirements

- Windows 64-bit with Windows Script Host enabled.
- Steam game version **1.7.1.0na**, build **25361591**. Other versions are refused.
- [Python 64-bit, version 3.11 or newer](https://www.python.org/downloads/windows/). Tested with Python 3.14.
- Internet access for the first installation.

## Install

1. Download **Code → Download ZIP** from this repository and fully extract it into a writable folder you intend to keep.
2. Double-click **Install-AutoLoot.vbs** and wait for confirmation.
3. Launch the game and load your save. AutoLoot starts automatically.

**Keep the installed folder in place.** No game files are replaced, and no compiler is needed.

## Pause, resume and uninstall

| File | Action |
| --- | --- |
| **Pause-AutoLoot.vbs** | Pause looting until you choose to resume, including after Windows restarts. |
| **Resume-AutoLoot.vbs** | Restore automatic operation. |
| **Uninstall-AutoLoot.vbs** | Stop AutoLoot and remove its Windows startup shortcut. After confirmation, delete the folder. |

An in-progress game call finishes before shutdown. If shutdown times out, the operation fails without force-killing a process; wait before retrying.

## Update

Extract the new version into a new folder and run its **Install-AutoLoot.vbs**. It stops the previous automatic installation, runs the checks and replaces its startup shortcut. After confirmation, you can delete the old folder.

When upgrading from an old version with manual launching, stop that version first using its own stop script.

## Limits

- Inventory limits still apply. AutoLoot does not force weapon swaps or bypass locked containers and separate opening actions.
- The radius is a distance check, so loot behind a thin wall may still be collected.
- The 100 ms interval waits for the next available player tick. Pauses, slow frames or game calls can delay it; large groups of objects are processed over several passes.
- Corpse, component and bag looting was confirmed in-game with the earlier 5 m / 250 ms settings. The current 2 m / 100 ms settings and automatic startup have passed offline checks; their next in-game confirmation is pending. Co-op remains unverified.

## Troubleshooting

If an action fails, its message points to a local log under `evidence/`. Watcher status and logs are in `evidence/autoloot5m/`; the directory name is historical, **the current radius is 2 m**.

If Steam detection fails, copy `autoloot.local.example.json` to `autoloot.local.json` and set `game_path` to the folder containing `ph_ft`:

```json
{"game_path": "D:/SteamLibrary/steamapps/common/Dying Light The Beast"}
```

You can also set `AUTOLOOT_GAME_PATH`. Do not disable the game-version checks. If VBS files cannot run, check whether Windows Script Host is disabled by your system policy.

## Development

Runtime sources and the Windows installer are in `tools/`; regression tests are in `tests/`.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe tools\autoloot_runtime.py --dummy
```

The installer runs the native fixture in a disposable process, never in the game. Tests cover distance, scheduling, refusal paths and normal shutdown; they do not prove inventory credit or co-op behavior. Local dependencies, logs, saves and game binaries are excluded from this repository.
