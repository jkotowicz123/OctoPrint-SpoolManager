# MMU single-nozzle routing

This feature lets an MK4 with MMU3 print ordinary single-nozzle G-code. The required material, color, and weight are embedded in the G-code by OrderManager. SpoolManager resolves that identity to one of five configured MMU slots when OctoPrint selects or starts the file.

Hardware movement is disabled by default. The defaults are:

- `mmuRoutingEnabled: false`
- `mmuRoutingDryRun: true`
- `mmuPrinterNumber: 5`
- `mmuLoadDistanceMm: 75`
- five empty slot assignments

## Safety model

- A missing, unsupported, or incomplete G-code contract is never guessed.
- Contracts with anything other than one used logical tool are rejected.
- Material and color must both match a configured active spool.
- The spool must have enough remaining weight, including the configured reserve.
- Live mode refuses to route while loaded state is `UNKNOWN`.
- Loaded state deliberately returns to `UNKNOWN` after every OctoPrint/plugin restart.
- Failed or cancelled prints return state to `UNKNOWN`.
- Standalone prints unload by default.
- ContinuousPrint retains filament only when its verified next path has the same material/color, resolves to the same physical spool, and that spool has enough weight for both prints.
- The separate Prusa MMU plugin should be disabled on printer #5 so only one plugin owns tool selection and unload behavior.

## Configuration API

The endpoint is `GET|PUT /plugin/SpoolManager/mmuRouting`. It returns slot assignments, loaded state, the active contract, the slot decision, and dry-run/live status.

Assign five SpoolManager spool database IDs and enable decision logging without hardware movement:

```json
{
  "enabled": true,
  "dryRun": true,
  "printerNumber": 5,
  "slotSpoolIds": [101, 205, null, 330, 441],
  "reserveWeight": 10,
  "loadDistanceMm": 75
}
```

Before the first live test, physically verify that the nozzle is empty and reconcile state:

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

Fresh-load mode preserves the ordinary single-nozzle start through mesh probing, expands the purge-area probe from W50 to W130, then injects the Prusa MMU3 setup, runtime `Tn`, 75 mm nozzle load, and long purge. The 75 mm transport is excluded from consumption; the 32 mm purge delta is charged to logical tool 0 and the selected physical spool.

Retained mode keeps the original W50 probe and short purge. JoBox's `E-6`, fan cooling, and 160 °C prelude are removed from the bounded end sequence in both live MMU modes. Unload mode inserts one `M702` before the end wait command.

OctoPrint `@SPOOLMANAGER` boundary commands are consumed by OctoPrint and are not sent to printer firmware. Unmarked and non-target G-code passes through unchanged.

## Printer #5 rollout

1. Install this feature branch and disable the Prusa MMU plugin.
2. Assign the five physical slots through the API.
3. Enable routing with `dryRun: true` and run both standalone and ContinuousPrint selections. Confirm the returned session decision and logs.
4. Test a virtual printer or disconnected serial capture and compare the emitted fresh/retained sequences.
5. With an empty nozzle, reconcile `UNLOADED`, switch `dryRun` off, and run a supervised purge-only test.
6. Run one supervised standalone print, a same-material two-item queue, and a material-change queue before production use.
