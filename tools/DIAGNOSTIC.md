# Plant and firearm diagnosis

Plant harvesting uses the exact already-open Container mode-2 route observed for lavender and chamomile, with the same guarded Take1/TakeAll interaction. Other plants sharing this mechanism are covered without item-name or rarity lists; inventory credit still requires in-game observation. The `--dropped-items` option adds the exact DroppedItem Take route. The watcher in this source tree enables it automatically; direct runtime commands must include the option. Updating these sources does not update an existing installation. This route covers the engine class, without selecting item types or rarity. Standard ground items still use the existing Take action, without rarity filtering. Inventory refusal and weapon swaps remain refused.

Run the offline qualification first from the repository in PowerShell:

```powershell
python tools/autoloot_runtime.py --dummy
```

For a later targeted in-game check, pause the installed AutoLoot using its Start menu shortcut and wait for it to stop. Load a save near **one** test object, with inventory space. Then, from this repository:

```powershell
python tools/autoloot_runtime.py --live --ground-items --containers --duration 60 --output evidence/plant-test.json
python tools/inspect_native.py --report evidence/plant-test.json
```

This collects normally through the existing guarded paths for 60 seconds; it does not enable unknown classes. The diagnostic adds no game reads or interactions. It retains sixteen distinct class/reason/stage samples and refreshes their last object address, collection cycle and cycle start time. Samples can be evicted when more classes/refusals are encountered. A reason of zero does not establish eligibility. The `unsupported_or_disabled_class` stage means no enabled route matched; `bind_refused` means the matching route failed preparation. Action refusals such as swap 24 remain in the ordinary `events` list. No collection or inventory credit is proven by a diagnostic sample.

Use a separate 60-second report for honey, each plant mechanism, an ordinary firearm and a legendary firearm, then a full-inventory firearm. Record the object label, whether the player was within 2 m, and inventory changes. The class resolver reads the installed game DLL only and prints its SHA256; compare it to the report preflight module hash. A null class name means RTTI resolution was unavailable, not that the object is safe to collect. The two reports and inventory observations provide the evidence needed to add an exact guarded route without enumerating item IDs.

After the command finishes and reports normal shutdown, resume installed AutoLoot from its Start menu shortcut. Do not run both collectors together. No installation or game-file replacement is needed for this check. The offline tests and the native fixture do not establish actual harvesting in game.


For a separately reviewed first DroppedItem trial, use the same pause/normal-shutdown sequence and limit dispatches:

```powershell
python tools/autoloot_runtime.py --live --dropped-items --duration 15 --max-dispatches 1 --output evidence/dropped-trial.json
```

The global cap applies to all enabled categories (corpses are also enabled by default). Verify the event body and `source_kind` identify the intended object. `dropped_source_changed` proves a successful read observed receiver generation or target invalidation after dispatch; it does not prove inventory credit. Read failures are unknown/no progress. Header and description identity, exact callback/type tables, inventory eligibility and Take1 remain required; swaps are refused.

To inspect a nearby object without collecting anything, use `--diagnostic-only`. It overrides all collection switches, including corpses; only the bounded spatial query and class observations remain active. The installed watcher must still be paused.

```powershell
python tools/autoloot_runtime.py --live --diagnostic-only --duration 15 --output evidence/observe-only.json
```

The single-item routes (`ContainerItem` and `DroppedItem`) refuse the engine's `OpportunityWeapon` property, including the observed pitchfork. Refusal reason `45` means this property was set; `44` means the description could not be validated or changed before dispatch. Inventory descriptions and the property are rechecked around action selection and eligibility. Ordinary throwables with this property clear remain eligible. The existing multiple-item corpse/container routes are unchanged; their payloads have not been individually qualified for opportunity-weapon exclusion.

`--containers` also enables the exact standalone `BodyContainer` bag route: mode 2, positive content count, no associated Human, and the validated CBS receiver. It uses Take1 with the engine's inventory eligibility checks. The corpse route and ordinary mode-1 container route keep their original guards. Bag progress is reported separately as `loot_bag` events and `bag_completed_count0_state5`; disappearance alone is not inventory-credit proof.

The mode-2 resource route is reported as `resource_container`, with separate `resource_dispatches` and `resource_completed_count0_state5` counters. It requires initially 1–512 contents, state 1, no nested container, exact owner/generation/callbacks and the existing radius. Mode 1 keeps the ordinary container route; unknown modes are refused (reason 47); failed reads retain their RPM refusal reason (100, 101 or 102). An opening action or weapon swap is never substituted for Take1.
