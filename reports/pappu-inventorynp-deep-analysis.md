# Pappu Inventory (NP 4.0 Style) Deep Analysis

## 1. File Structure (Summary)
- **Root**: `fxmanifest.lua`, `config.lua`, `HPX-inventory.sql`.
- **Client**: `main.lua` (Input handling, hotbar, weapon effects), `visual.lua` (Drop markers/objects).
- **Server**: `main.lua` (Core logic, Item adding/removing, Decay system), `compat_qb.lua` (Legacy event handlers), `shop_compat.lua` (Shop bridging).
- **Shared**: `qbcore_compat.lua` (Framework abstraction).
- **HTML**: Complete NUI build with Gilroy fonts and 150+ item/weapon/attachment images.

## 2. API: Exports and Events
### Exports (Server)
- `AddItem`, `RemoveItem`, `HasItem`
- `GetItemByName`, `GetItemsByName`, `GetItemBySlot`
- `LoadInventory`, `SaveInventory`, `ClearInventory`
- `SetInventory`, `SetItemData`
- `OpenInventory`, `OpenInventoryById`
- `RegisterShopItems`, `CreateUsableItem`
- `addTrunkItems`, `addGloveboxItems`

### Exports (Client)
- `HasItem`

### Major Events
- `inventory:client:OpenInventory`
- `inventory:server:OpenInventory`
- `inventory:server:SetInventoryData` (Main move/swap logic)
- `inventory:server:UseItemSlot`
- `qb-inventory:server:SaveStashItems`

## 3. Dependencies
- **Mandatory**: `qb-core` (or `qbox-core`), `oxmysql`.
- **Resource References**: `@qb-weapons/config.lua` (must exist), `@qb-core/shared/locale.lua`.
- **Optional/Integrations**: `qb-target`, `ir_skeleton`, `ps-mdt`, `qb-traphouse`, `qb-methlab`.

## 4. SQL Comparison
| Table | Pappu Inventory | Standard QBCore | Notes |
| :--- | :--- | :--- | :--- |
| `stashitems` | `id`, `stash`, `items` (longtext) | Identical | Safe to use existing data if schema matches. |
| `trunkitems` | `id`, `plate`, `items` (longtext) | Identical | Safe to use existing data. |
| `gloveboxitems` | `id`, `plate`, `items` (longtext) | Identical | Safe to use existing data. |
| `player_vehicles` | Complete definition in SQL | Exists in live server | **CRITICAL**: Do not run this SQL part on a live server. |

## 5. Feature Support Matrix
- **Stashes/Trunks/Gloveboxes**: ✅ Fully supported.
- **Shops**: ✅ Supported via `RegisterShopItems`.
- **Item Metadata**: ✅ Robust support via `info` table.
- **Weapon Metadata**: ✅ Serials, attachments, and durability.
- **Item Decay**: ✅ Integrated system using `item.decay` from Shared.Items.
- **Hotbar**: ✅ Included (Keybind 'Z' by default).
- **Attachments**: ✅ Visual and functional support.
- **Crafting**: ✅ Included for general items and attachments.
- **Evidence**: ✅ Serial number generation and MDT integration.

## 6. Likely Breaking Points
- **Item Images**: If custom items on the server use paths not in `html/images/`, they will show as broken icons.
- **Stash/Trunk Access**: If other scripts call `TriggerServerEvent('inventory:server:OpenInventory', ...)` with old parameters, they might need adjustment (though `compat_qb.lua` handles many).
- **Custom Metadata**: Scripts relying on very specific `info` sub-keys should be checked.

## 7. Migration Risks
- **Replacement vs Parallel**: You cannot run this alongside `ps-inventory`. You must stop the old one.
- **Data Persistence**: Ensure `oxmysql` is running and the database tables exist.
- **Client Performance**: The NP 4.0 UI is heavier than the default QBCore inventory. Monitor client-side NUI lag.

## 8. Rollback Checklist
- [ ] **Step 1**: Stop `pappu-inventorynp`.
- [ ] **Step 2**: Restore original `qb-inventory` or `ps-inventory` in `server.cfg`.
- [ ] **Step 3**: Revert any database changes (if `stashitems`, etc., were modified).
- [ ] **Step 4**: Restart server or ensure resources are fully reloaded.
- [ ] **Step 5**: Verify original items are back in player inventories.
