# Better AutoLoot — Dying Light: The Beast

Automatically loot corpses, crafting components, bags and supported containers within **2 metres**, with a **100 ms target interval**. No aiming or interaction key required.

Runs invisibly in the background, checks for the game every **10 seconds**, and stops looting when the game closes.

## Install or update

1. Close the game.
2. Download the setup EXE from [the latest release](https://github.com/Rhadamanthe0/dying-light-the-beast-autoloot/releases/latest) or the mod's Nexus Files tab.
3. Run setup and allow a few minutes for its offline checks, then launch the game.

**No Python installation or Internet connection is needed during setup.** Everything is included. The download can be deleted afterward.

Installs for your Windows account in `%LOCALAPPDATA%\Programs\Better AutoLoot` by default. You can choose another empty, dedicated folder; keep it outside the game folder. The watcher starts automatically after installation and at Windows sign-in. Updates preserve an existing pause.

## Pause or uninstall

- **Start menu → Better AutoLoot → Pause AutoLoot** pauses looting, including after Windows restarts.
- **Resume AutoLoot** enables it again.
- Uninstall through **Windows Settings → Apps → Better AutoLoot**, or its Start menu uninstall shortcut.

## Compatibility

- Windows 10/11 x64; run the game and mod under the same account and privilege level.
- Supports **Steam executable 1.7.1.0na, build 25361591**. Unsupported game updates require a new qualified mod release.
- Respects inventory limits. Does not swap weapons, unlock containers or perform separate opening steps.
- No wall visibility check: nearby loot can pass through thin walls. Pauses, slow frames and large groups can delay the 100 ms target.
- Current 2 m / 100 ms settings and automatic startup still await in-game confirmation. **Co-op remains unverified.**

## Troubleshooting

Wait up to 10 seconds after loading a game and check that AutoLoot is not paused. If shutdown times out, wait before retrying; pending game calls must finish.

Logs are in the installed folder: `evidence\Configure-AutoLoot.log` for setup and `evidence\autoloot5m\watch.log` for startup errors. If Steam detection fails, copy `autoloot.local.example.json` to `autoloot.local.json` there and set `game_path` to the game's installation folder.

<details>
<summary>Publishing releases</summary>

Update `VERSION` in `tools/build_installer.py`, commit, and push the matching `vMAJOR.MINOR.PATCH` tag. GitHub builds, tests and publishes the installer automatically. **Actions → Build and publish installer → Run workflow** rebuilds an existing tag.
</details>
