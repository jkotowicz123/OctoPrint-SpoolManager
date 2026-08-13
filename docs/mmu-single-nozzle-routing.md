# MMU single-nozzle routing

This feature lets an MK4 with MMU3 print ordinary single-nozzle G-code. The required material, color, and weight are embedded in the G-code by OrderManager. SpoolManager resolves that identity to one of five configured MMU slots when OctoPrint selects or starts the file.

Hardware movement is disabled by default. The defaults are:

- `mmuRoutingEnabled: false`
- `mmuRoutingDryRun: true`
- `mmuPrinterNumber: 5`
- `mmuLoadDistanceMm: 17`
- MMU positions reuse the existing SpoolManager Tool 0-4 sidebar assignments

## Safety model

- A missing, unsupported, or incomplete G-code contract is never guessed.
- Contracts with anything other than one used logical tool are rejected.
- Material and color must both match a configured active spool.
- The spool must have enough remaining weight, including the configured reserve.
- Live mode recovers `UNKNOWN` state with non-interactive `M702 W255` after the nozzle reaches the sliced first-layer temperature and before selecting a slot.
- Loaded state deliberately returns to `UNKNOWN` after every OctoPrint/plugin restart.
- Prusa MMU events and MK4 MMU progress messages confirm completed loads and unloads; sending an extrusion command alone never marks a load successful.
- Failed, cancelled, disconnected, or ambiguous prints return state to `UNKNOWN`.
- Standalone prints unload by default.
- ContinuousPrint retains filament only when its verified next path has the same material/color, resolves to the same physical spool, and that spool has enough weight for both prints.
- The Prusa MMU plugin may remain installed for its navbar and supplies action-completion events. Its single-filament rewrite/prompt must remain disabled so SpoolManager alone owns routing.
- Exact maintenance filenames `Swap Plate with Doors.gcode`, `Swap Plate with Doors-2.gcode`, `Jobox Load Plate.gcode`, and `Jobox Eject Plate.gcode`, or files containing `; SPOOLMANAGER_ROUTING_BYPASS = maintenance`, bypass routing without changing the remembered loaded state.
- Fresh-load purge uses `mmuPurgePasses` (1–3, default 2). Every pass keeps the MMU3 `E/X = 0.4` ratio and `F500/F650/F800` progression and extrudes continuously at Z0.2. Each additional pass shifts 2 mm toward the bed in Y with a matching 0.8 mm extrusion, then reverses X direction to form one connected zigzag that is easy to remove from the sheet.

## Configuration API

The endpoint is `GET|PUT /plugin/SpoolManager/mmuRouting`. It returns slot assignments, loaded state, the active contract, the slot decision, and dry-run/live status.

Assign spools with the existing five sidebar selectors. Tool 0 is MMU position 1,
Tool 1 is position 2, through Tool 4 as position 5. The API may also update the
same visible assignments and enable decision logging without hardware movement:

```json
{
  "enabled": true,
  "dryRun": true,
  "printerNumber": 5,
  "slotSpoolIds": [101, 205, null, 330, 441],
  "reserveWeight": 10,
  "loadDistanceMm": 17
}
```

Loaded state may still be reconciled manually while idle, but it is no longer required after an OctoPrint restart. An unknown state triggers the safe recovery unload:

```json
{
  "loadedState": "UNLOADED"
}
```

If filament is already loaded, identify its MMU slot explicitly:

```json
{
  "loadedState": "LOADED",
  "loadedSlot": 2
}
```

State cannot be reconciled while printing or paused.

## Runtime behavior

Fresh-load mode preserves the ordinary single-nozzle start through mesh probing, expands the purge-area probe from W50 to W235, then injects the Prusa MMU3 setup, optional non-interactive `M702 W255` recovery, restores the bed/nozzle targets cleared by recovery, selects runtime `Tn`, performs the profile-accurate 17 mm nozzle load, and purges along the front edge. With the default two passes it extrudes about 176 mm total in the purge sequence: the first pass runs to X225 at Y-4, an extruded 2 mm Y connector moves to Y-2, the second pass returns to X15, and the wipe exits toward X9 without crossing the purge lines. The 17 mm transport is excluded from consumption; the 156.8 mm purge delta is charged to logical tool 0 and the selected physical spool.

Retained mode keeps the original W50 probe and short purge. JoBox's `E-6`, fan cooling, and 160 °C prelude are removed from the bounded end sequence in both live MMU modes. Unload mode inserts one `M702` before the end wait command, then raises Z by 5 mm in relative mode and restores absolute coordinates before shutting down the hotend.

OctoPrint `@SPOOLMANAGER` boundary commands are consumed by OctoPrint and are not sent to printer firmware. Unmarked and non-target G-code passes through unchanged.

## Printer #5 rollout

1. Install this feature branch. Keep the Prusa MMU navbar enabled, but disable its single-filament prompt/rewrite.
2. Assign the five physical slots with the existing SpoolManager sidebar selectors.
3. Enable routing with `dryRun: true` and run both standalone and ContinuousPrint selections. Confirm the returned session decision and logs.
4. Test a virtual printer or disconnected serial capture and compare the emitted fresh/retained sequences.
5. Switch `dryRun` off and run a supervised recovery/load/full-width-purge test.
6. Run one supervised standalone print, a same-material two-item queue, and a material-change queue before production use.
