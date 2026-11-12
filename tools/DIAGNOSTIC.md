# Optional pickup diagnosis

These procedures are available for investigating a particular object. See the [version-specific in-game evidence and limits](../README.md#compatibility) before interpreting a result. Updating this source tree does not update an existing installation.

## Offline qualification

From the repository in PowerShell, qualify each profile separately when its compiled core or fixture has changed:

```powershell
python tools/autoloot_runtime.py --dummy --profile 1.7.1.0na
python tools/autoloot_runtime.py --dummy --profile 1.8.1.0na
```

Each command exercises a disposable child process, without accessing the game. The proofs have distinct names in `evidence` and bind the exact profile, compiled C core and fixture. The installer runs both qualifications locally. Offline results do not prove inventory credit in game. `--profile` selects only the offline fixture; live commands detect the exact installed game/DLL fingerprints.

## Observe without collecting

Pause the installed AutoLoot using its Start menu shortcut and wait for normal shutdown before running another runtime. During normal gameplay, this optional command observes nearby classes for 15 seconds with every collection route disabled:

```powershell
python tools/autoloot_runtime.py --live --diagnostic-only --duration 15 --output evidence/observe-only.json
python tools/inspect_native.py --report evidence/observe-only.json
```

The report retains up to sixteen distinct class/reason/stage samples. Repeated samples refresh their object address, cycle and cycle start time; later classes can evict earlier samples. `unsupported_or_disabled_class` means no enabled route matched. `bind_refused` means preparation of the matching route failed. A reason of zero does not establish eligibility. A sample alone proves neither collection nor inventory credit.

The class resolver reads the installed game DLL on disk and prints its SHA256. Compare that hash to the report's preflight module hash. A null class name means RTTI resolution was unavailable; it does not establish that an object is eligible.

## Optional bounded pickup

For a chosen nearby object, with inventory space, this command enables the existing routes for at most 15 seconds and one native dispatch:

```powershell
python tools/autoloot_runtime.py --live --ground-items --dropped-items --containers --duration 15 --max-dispatches 1 --output evidence/pickup-test.json
python tools/inspect_native.py --report evidence/pickup-test.json
```

The cap is global and includes corpses, which are enabled by default. Match the event's object and `source_kind` to the intended object. Record the visible item and inventory change if inventory-credit evidence is needed. A time limit requests a cooperative stop; it cannot preempt an engine call already in progress.

The optional 1.8.1 trial mode can restrict a pickup to one category (`corpses`, `ground`, `dropped` or `containers`):

```powershell
python tools/autoloot_runtime.py --live --trial-181 --trial-category dropped --duration 15 --max-dispatches 1 --output evidence/dropped-trial.json
```

This mode is limited to 30 seconds and an explicit dispatch cap from 1 to 64. Do not combine it with the legacy collection switches. It remains an optional diagnostic tool; normal 1.8.1 operation does not require `--trial-181`.

After normal shutdown is confirmed, resume the installed AutoLoot from its Start menu shortcut. Never run the installed collector and a direct diagnostic runtime together.

## Routes and refusal evidence

- `--dropped-items` enables the exact DroppedItem Take route; the watcher enables it automatically. Standard ground items use their existing Take route. Both retain exact type, ownership, callback, generation, inventory-description and eligibility guards. The 1.8.1 CBS routes accept only the exact CoGameObjectProxy or CoModelObjectProxy table. The table selected at binding must remain unchanged.
- Single-item `ContainerItem` and `DroppedItem` routes refuse the engine's `OpportunityWeapon` property. Reason `45` reports that property; `44` reports an unvalidated or changing description. The description and property are rechecked around action selection and eligibility. Weapon swaps remain refused, including action reason `24`.
- `--containers` also enables standalone BodyContainer loot bags: mode 2, positive content count, no associated Human and the exact validated CBS receiver. They are reported as `loot_bag`, with `bag_completed_count0_state5` progress counters.
- Ready-to-take plants use the guarded Container mode-2 resource mechanism, without plant-name or rarity lists. These events are `resource_container`, with separate dispatch, refusal and completion counters. They require 1 to 512 initial contents, state 1, no nested container and the exact owner, generation and callbacks. Ordinary containers retain mode 1. Unknown modes are refused with reason `47`; read/budget failures retain reasons `100`, `101` or `102`. No opening action substitutes for Take1.

`dropped_source_changed` records a successfully read receiver-generation or target change after dispatch. Count-zero/state-five counters describe source progress. Neither source disappearance nor these counters alone establish inventory credit. Failed reads remain unknown or no progress. Multiple-item corpse/container payloads have not been individually qualified for opportunity-weapon exclusion.
