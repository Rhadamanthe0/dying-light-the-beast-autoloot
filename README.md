# Better AutoLoot — Dying Light: The Beast

Automatically loot nearby corpses, crafting components, bags and supported containers.

- **2 metre radius**, with a **100 ms** target scan interval.
- No aiming or interaction key required.
- Starts when the game is detected; stops looting when the game closes.
- Runs in the background with no command window.

The background watcher checks for the game every **10 seconds**. The 100 ms loot interval applies while player updates are advancing.

## Install

1. Close the game.
2. Download **BetterAutoLoot-Setup-1.1.0.exe** from the mod's Files tab or the repository's Releases page.
3. Run the installer and finish setup. Offline checks may take a few minutes.
4. Launch the game and play.

**No Python installation, package manager or separate runtime is required.** Everything is included; setup works offline. The download folder can be deleted afterward.

The default location is `%LOCALAPPDATA%\Programs\Better AutoLoot`. Setup installs for your Windows account and starts the watcher immediately and at Windows sign-in. You can choose another empty, dedicated folder; do not install into the game folder.

To update, close the game and run the new installer. Setup safely stops the previous installation before replacing files. An existing pause is preserved. Old source installations are stopped and their startup shortcut is replaced; their download folder is left for you to delete.

## Pause or uninstall

- **Start menu → Better AutoLoot → Pause AutoLoot** suspends automatic looting, including after Windows restarts.
- **Resume AutoLoot** enables it again.
- Uninstall through **Windows Settings → Apps → Better AutoLoot**, or the Start menu uninstall shortcut. This stops AutoLoot and removes its startup shortcut and installed files.

An in-progress game call finishes before shutdown. If shutdown times out, the operation fails without force-killing a process; wait before retrying.

## Compatibility and limits

- Windows 10/11, x64. Run the game and mod under the same Windows account and privilege level.
- Qualified for **Steam executable version 1.7.1.0na**, build **25361591**. Exact executable and engine checks reject unsupported updates.
- Inventory limits still apply. Weapon swaps are not forced; locked containers and separate opening actions are excluded.
- The radius has no wall visibility check, so loot can still pass through thin walls.
- Pauses, slow frames and game calls can delay the 100 ms target interval. Large groups are processed over several passes.
- Corpses, components and bags were confirmed in game with earlier 5 m / 250 ms settings. Current 2 m / 100 ms settings and automatic startup have passed offline checks; live confirmation remains pending. Co-op remains unverified.

## Troubleshooting

Wait up to 10 seconds after loading a game and check that AutoLoot is not paused. If Steam detection fails, copy `autoloot.local.example.json` to `autoloot.local.json` in the installed folder and set `game_path` to the folder containing `ph_ft`:

```json
{"game_path": "D:/SteamLibrary/steamapps/common/Dying Light The Beast"}
```

Logs are in the installed folder's `evidence` directory. Check `Configure-AutoLoot.log` for installation failures and `autoloot5m\watch.log` / `watch-status.json` for startup or game-version errors. The `autoloot5m` directory name is historical; the radius is **2 m**. An unsupported game update requires a new qualified mod release.

## Build from source

Players only need the installer. Developers need Windows x64, Python 3.14 x64, network access for the first build, and [Inno Setup 6.7.3](https://jrsoftware.org/isdl.php). The compiler is a build tool and is not required by players.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe tools/build_installer.py --iscc "C:\Path\To\Inno Setup 6\ISCC.exe"
```

The builder verifies pinned downloads, bundles the official Python embeddable distribution with complete dependency wheels, runs offline native qualification against its own disposable process, then creates the installer in `dist`. No game files or local runtime state are distributed. Third-party licenses remain with their packages.

## GitHub Releases

The **Build and publish installer** workflow builds the EXE on GitHub's Windows runners, runs the regression and embedded-runtime checks, then attaches the installer and its SHA256 checksum to GitHub Releases. Publishing runs only after successful checks.

To release a new version, update `VERSION` in `tools/build_installer.py`, commit the change, then push the matching tag (for example `v1.2.0`). The workflow creates the Release automatically. To rebuild an existing version, open **Actions → Build and publish installer → Run workflow** on `main` and enter its existing tag, such as `v1.1.0`. It builds that tag's source and replaces its release files without changing the release description.

For source-only setup, `Install-AutoLoot.vbs` creates a local virtual environment and requires Python 3.11+ x64 and Internet access. Its companion Pause, Resume and Uninstall helpers control that source installation. The EXE installer is the recommended player installation.
