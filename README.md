# Better AutoLoot: Dying Light: The Beast

Source version **1.4.0**. Automatically loot eligible corpses, ground items, inventory weapons, leftover loot bags and supported plant/container mechanisms within **2 metres**, with a **100 ms target interval**. No aiming or interaction key required.

Runs invisibly in the background, checks for the game every **10 seconds**, and stops looting when the game closes.

## Install or update

1. Close the game.
2. Download the setup EXE from [the latest release](https://github.com/Rhadamanthe0/dying-light-the-beast-autoloot/releases/latest) or the mod's Nexus Files tab.
3. Run setup and allow a few minutes for its offline checks, then launch the game.

**No Python installation or Internet connection is needed during setup.** Everything is included. The download can be deleted afterward.

Installs for your Windows account in `%LOCALAPPDATA%\Programs\Better AutoLoot` by default. You can choose another empty, dedicated folder; keep it outside the game folder. The watcher starts automatically after installation and at Windows sign-in. Updates preserve an existing pause.

## Automatic updates

At Windows sign-in, the watcher checks GitHub for a newer stable release, then checks again every 24 hours while it runs. Internet access is needed for these checks and downloads. Offline failures are retried without interrupting collection.

An update is installed silently after the game closes. The downloaded installer must match a release manifest signed by the mod's pinned update key. Updates preserve a manual pause and the installation folder. Unsupported game updates still require a qualified compatibility profile.

## Pause or uninstall

- **Start menu → Better AutoLoot → Pause AutoLoot** pauses looting, including after Windows restarts.
- **Resume AutoLoot** enables it again.
- Uninstall through **Windows Settings → Apps → Better AutoLoot**, or its Start menu uninstall shortcut.

## Compatibility

- Windows 10/11 x64; run the game and mod under the same account and privilege level.
- Supports the exact Steam builds listed below. Unknown game/DLL fingerprints are refused; an update requires a new qualified profile.
- Uses the engine's inventory eligibility checks. Does not swap weapons, unlock containers or perform separate opening steps.
- Collects supported ground weapons without type, rarity or quality filters. Individual pickups marked by the engine as opportunity weapons (such as the tested pitchfork) are left in place.
- Harvests plants using the supported ready-to-take container mechanism; no plant-name list is needed.
- No wall visibility check: nearby loot can pass through thin walls. Pauses, slow frames and large groups can delay the 100 ms target.
- The 100 ms interval remains a target. Startup at Windows sign-in remains unverified. Pause/menu/death behavior and **co-op remain unverified in game**. Multiple-item corpse/container payloads have not been individually qualified for opportunity-weapon exclusion.

| Steam executable | Steam build | In-game evidence |
| --- | --- | --- |
| **1.7.1.0na** | **25361591** | Earlier checks confirmed lavender, chamomile, a common C515 carbine, a military axe and leftover loot bags. An opportunity pitchfork remained untouched. |
| **1.8.1.0na** | **26402545** | Corpses were collected without aiming or pressing an interaction key, including on approach at a measured **1.92255 m**. Retrieving **Poinçonneuse** increased weapon inventory from **7 to 8 of 16** slots. Runtime counters recorded **three emptied loot bags**; the user confirmed pickup and also confirmed automatic collection of ground objects. |

Individual ground-item types and other plant and container mechanisms on 1.8.1 rely on the existing guarded paths and local tests; they have not been separately verified in game on that version. Full-inventory, weapon-swap and opportunity-weapon refusals are retained and covered by local tests. A full-inventory trial was not repeated in game on 1.8.1. Legendary weapons have not been individually verified on either version.

For the next game update, follow the [profile qualification procedure](tools/DIAGNOSTIC.md#qualifying-a-new-game-build).

## Troubleshooting

Wait up to 10 seconds after loading a game and check that AutoLoot is not paused. If shutdown times out, wait before retrying; pending game calls must finish.

Logs are in the installed folder: `evidence\Configure-AutoLoot.log` for setup and `evidence\autoloot5m\watch.log` for startup errors. If Steam detection fails, copy `autoloot.local.example.json` to `autoloot.local.json` there and set `game_path` to the game's installation folder.

<details>
<summary>Building and publishing releases</summary>

From a Windows source checkout with the build dependencies installed:

```powershell
python tools/build_installer.py --stage-only
python tools/build_installer.py --iscc "C:\path\to\ISCC.exe"
```

Both commands stage a fresh embedded runtime and run the native fixture separately for both game profiles. `--stage-only` stops before installer compilation. Neither command installs or starts AutoLoot. Build reports are saved under `.build/reports`; the full build produces `dist/BetterAutoLoot-Setup-1.4.0.exe`.

The release workflow requires the repository secret `AUTOLOOT_UPDATE_SIGNING_KEY` to sign the update manifest. Keep that private key outside the source tree. Update `VERSION` in `tools/mod_version.py`, commit, and push the matching `vMAJOR.MINOR.PATCH` tag. GitHub builds, tests and publishes the installer automatically. **Actions → Build and publish installer → Run workflow** rebuilds an existing tag.

All workflows run on GitHub-hosted runners (`windows-latest` for the Windows jobs, `ubuntu-latest` for publication).
</details>
