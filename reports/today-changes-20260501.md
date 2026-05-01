# FiveM QBCore Server Changes - 2026-05-01

This report documents the approved staged server integration work completed on May 1, 2026.

## Safety Notes

- SQL was not run.
- `qb-core` was not edited for inventory work.
- The live `qb-inventory` backend was not replaced.
- `incoming/qb-inventory-new` was investigated only and was not applied.
- Live inventory remains `[qb]/qb-inventory` version 2.0.0.
- Inventory changes were limited to `qb-inventory/html/main.css`.
- Old resources were backed up before live edits.

## Backup Paths

- Safe HUD/weapons apply: `/home/agentzero/agents/backups/20260501-022315-safe-plus-hud-weapons`
- Chat fix: `/home/agentzero/agents/backups/20260501-024043-chat-fix`
- Loading details default hidden: `/home/agentzero/agents/backups/20260501-loading-details`
- Loading music and vehicle locks: `/home/agentzero/agents/backups/20260501-025200-lockscreen-vehiclelocks`
- Vehicle tuning and inventory UI: `/home/agentzero/agents/backups/20260501-030752-vehicle-tuning-inventory-ui`

## Safe HUD, Weapons, Ambulance, Standalone Resources

Approved safe-plus-HUD/weapons path was applied after backups.

Changes included:

- Merged low-risk `qb-ambulancejob/config.lua` bed coordinate changes.
- Replaced/tested `qb-hud`.
- Replaced/tested `qb-weapons`.
- Added fresh standalone resources:
  - `chat-main`
  - `cylex_animmenuv2`
  - `map-atlas`

No database changes were made.

## ox_lib Handling

The uploaded `ox_lib` was found incomplete because its web build output was missing.

Result:

- The incomplete live `[standalone]/ox_lib` addition was removed.
- The uploaded incomplete copy remains in `incoming`.
- Nothing was downloaded from the internet.

Restart safety was improved by avoiding an incomplete ensured resource.

## Chat Fix

The default FiveM/QBCore chat was disabled in favor of `chat-main`.

Changes included:

- `server.cfg` now sets `resources_useSystemChat false`.
- Default `ensure chat` was disabled.
- `chat-main` remains the intended chat input/UI.
- Fixed `chat-main/cl_chat.lua` table concatenation error by normalizing chat type values before string use.
- Chat input was bound to `T`.
- `L` was kept available for vehicle lock/unlock.

## Loading Screen

Music behavior:

- Loading music is off by default.
- The existing audio toggle remains available so players can turn music on manually.
- The audio feature was not removed.

Details behavior:

- Loading details are hidden/collapsed by default.
- The existing downloading/details button still opens the details panel manually.
- The details feature was not removed.

Changed loading files:

- `[qb]/qb-loading/html/app.js`
- `[qb]/qb-loading/html/index.html`

## NPC Vehicle Lock Behavior

Vehicle lock behavior was made config-driven in `qb-vehiclekeys`.

Added/used config:

```lua
Config.DrivingNpcVehicleLocked = false
Config.ParkedVehicleLockChance = 80
Config.AdvancedLockpickClasses = {
    [6] = true,
    [7] = true,
}
```

Behavior:

- NPC vehicles actively driving on the road default unlocked.
- Parked NPC/world vehicles have an 80% chance to be locked.
- Parked vehicle lock state is cached client-side per vehicle during the client session.
- Sports and super vehicles require `advancedlockpick`.
- Normal lockpick is rejected for configured advanced classes.

## Vehicle Lockpick and Hotwire Tuning

Added/used config:

```lua
Config.HotwireTimeMin = 5000
Config.HotwireTimeMax = 8000
Config.VehicleLockpickSkillbarSpeedScale = 0.75
```

Behavior:

- Successful parked-vehicle lockpick unlocks the vehicle.
- Lockpick from outside does not grant permanent keys.
- Player can enter the unlocked vehicle and press `H` to hotwire.
- Hotwire progress now takes 5-8 seconds.
- Vehicle lockpick skillbar is 25% slower.
- The slowdown is per-call for vehicle lockpick only; other skillbar minigames keep default speed.
- Hotwire repeat spam during progress was reduced by not clearing `IsHotwiring` until the progress callback completes.

Changed vehicle/minigame files:

- `[qb]/qb-vehiclekeys/config.lua`
- `[qb]/qb-vehiclekeys/client/main.lua`
- `[qb]/qb-minigames/client/skillbar.lua`
- `[qb]/qb-minigames/html/js/skillbar.js`

## Inventory UI Overhaul

The live inventory backend was not replaced.

Preserved:

- live `[qb]/qb-inventory` backend
- live `qb-inventory` client logic
- live `qb-inventory/html/app.js`
- live NUI actions and callbacks
- database model
- exports

Not done:

- did not run HPX inventory SQL
- did not apply `incoming/qb-inventory-new` backend
- did not touch `qb-core/shared/items.lua`

Changed:

- `[qb]/qb-inventory/html/main.css`

UI direction applied:

- dark transparent glass panels
- cyan/blue accents matching `chat-main`
- cyan borders and glow
- cleaner item slots
- rounded panels
- subtle blur
- modern readable labels
- refreshed weight bars
- refreshed hotbar
- refreshed item notifications
- refreshed required-item display
- refreshed context menus/tooltips

## Validation Performed

Passed:

- `node --check` for `qb-loading/html/app.js`
- `node --check` for `qb-minigames/html/js/skillbar.js`
- `node --check` for `qb-inventory/html/app.js`

Not available:

- Local Lua compiler was not installed, so Lua syntax could not be compiler-checked locally.

## Test Checklist

Loading screen:

- Confirm music is silent by default.
- Confirm music can be enabled manually with the settings toggle.
- Confirm details panel is hidden by default.
- Click the details/download button and confirm details can be shown manually.

Chat:

- Confirm only `chat-main` UI appears.
- Press `T` and confirm chat input opens.
- Press `L` and confirm chat does not open.
- Confirm vehicle lock/unlock still uses `L`.

Vehicle keys:

- Try entering NPC-driven road vehicles; they should be unlocked.
- Try several parked NPC/world vehicles; about 80% should be locked.
- Lockpick a parked locked vehicle.
- Confirm success unlocks the vehicle but does not grant keys from outside.
- Enter the vehicle and confirm `H` hotwire prompt appears.
- Press `H`; hotwire should take 5-8 seconds.
- Confirm hotwire cannot be spammed while already in progress.
- Confirm sports/super vehicles require `advancedlockpick`.
- Confirm unrelated skillbar minigames are not slowed.

Inventory:

- Open inventory.
- Open stash, trunk, glovebox, and shop inventories.
- Drag/drop items between slots.
- Drop item to ground.
- Give item.
- Use item.
- Split stack.
- Confirm hotbar display.
- Confirm item box notification.
- Confirm required item notification.
- Confirm weapon attachment panel.
- Watch F8 for NUI/CSS errors.

HUD/weapons:

- Confirm HUD renders.
- Confirm weapon use/ammo/attachment behavior.
- Confirm ambulance bed coordinates match the map.

## Rollback Notes

Restore the corresponding files from the backup folders listed above.

For the loading details/music change, restore:

- `[qb]/qb-loading/html/app.js`
- `[qb]/qb-loading/html/index.html`

For vehicle lock and hotwire behavior, restore:

- `[qb]/qb-vehiclekeys/config.lua`
- `[qb]/qb-vehiclekeys/client/main.lua`
- `[qb]/qb-minigames/client/skillbar.lua`
- `[qb]/qb-minigames/html/js/skillbar.js`

For inventory UI, restore:

- `[qb]/qb-inventory/html/main.css`

For chat, restore:

- `server.cfg`
- `[standalone]/chat-main/cl_chat.lua`

For HUD/weapons/standalone resource replacements, restore from:

- `/home/agentzero/agents/backups/20260501-022315-safe-plus-hud-weapons`

