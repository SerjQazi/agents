# FiveM Patch Plan

Generated: 2026-05-01T00:18:31
Staged script: `/home/agentzero/agents/staging/test-bad-script`
Server: `/home/agentzero/fivem-server/txData/QBCore_F16AC8.base`

## Summary of Detected Issues

- Manifest present at script root: yes
- Files scanned: 3
- framework: ESX
- inventory: ox_inventory
- target: ox_target
- database: mysql-async

## Risk Flags
- Script appears ESX-based and needs QBCore compatibility work.
- Script expects ox_inventory, but this server uses qb-inventory.
- Script expects ox_target, but this server uses qb-target.
- Script uses mysql-async patterns and should be adapted to oxmysql.

## Adaptation Plan
1. Keep the first pass read-only; produce this report before editing.
2. Do not edit qb-core directly.
3. Backup the incoming script folder before any changes.
4. Use AGENT FIX START and AGENT FIX END markers around major generated edits.
5. Add or convert framework access to QBCore inside the incoming script.
6. Create a qb-inventory compatibility adapter for item checks and item mutations.
7. Map ox_target registrations to qb-target equivalents inside the incoming script.
8. Convert database calls to oxmysql syntax only after reviewing query behavior.
9. Stop for approval before schema, inventory core, money, permissions, or player data changes.

## Suggested Code Fixes

These are read-only examples for the incoming script. They are not patches, do not overwrite full files, and must not be applied to qb-core or live server resources.

### ESX to QBCore framework access

- Status: likely relevant
- Apply only inside the incoming script after review and backup.

```lua
-- AGENT FIX START: replace ESX player lookup with QBCore player lookup inside the incoming script
local QBCore = exports['qb-core']:GetCoreObject()

RegisterNetEvent('example:server:action', function()
    local src = source
    local Player = QBCore.Functions.GetPlayer(src)

    if not Player then
        return
    end

    local citizenid = Player.PlayerData.citizenid
    -- Continue using citizenid or Player.Functions APIs in this resource.
end)
-- AGENT FIX END
```

### ox_inventory to qb-inventory item check and remove

- Status: likely relevant
- Apply only inside the incoming script after review and backup.

```lua
-- AGENT FIX START: replace ox_inventory item count and removal with QBCore player item APIs
local QBCore = exports['qb-core']:GetCoreObject()

RegisterNetEvent('example:server:takeItem', function()
    local src = source
    local Player = QBCore.Functions.GetPlayer(src)

    if not Player then
        return
    end

    local item = Player.Functions.GetItemByName('lockpick')
    if item and item.amount > 0 then
        Player.Functions.RemoveItem('lockpick', 1)
        TriggerClientEvent('inventory:client:ItemBox', src, QBCore.Shared.Items['lockpick'], 'remove')
    end
end)
-- AGENT FIX END
```

### ox_target to qb-target box zone

- Status: likely relevant
- Apply only inside the incoming script after review and backup.

```lua
-- AGENT FIX START: replace ox_target zone registration with qb-target AddBoxZone
CreateThread(function()
    exports['qb-target']:AddBoxZone(
        'test_bad_script_open',
        vector3(0.0, 0.0, 72.0),
        1.5,
        1.5,
        {
            name = 'test_bad_script_open',
            heading = 0.0,
            minZ = 71.0,
            maxZ = 73.0,
        },
        {
            options = {
                {
                    icon = 'fa-solid fa-box',
                    label = 'Open stash',
                    action = function()
                        TriggerEvent('test-bad-script:client:openStash')
                    end,
                },
            },
            distance = 2.0,
        }
    )
end)
-- AGENT FIX END
```

### mysql-async to oxmysql query

- Status: likely relevant
- Apply only inside the incoming script after review and backup.

```lua
-- AGENT FIX START: replace mysql-async callback query with oxmysql await query
local rows = MySQL.query.await(
    'SELECT * FROM players WHERE citizenid = ?',
    { citizenid }
)

print(('oxmysql result count: %s'):format(#rows))
-- AGENT FIX END
```

## Read-Only Guardrails

- This plan is not a patch and does not overwrite full files.
- Apply changes only inside the staged script after review.
- Do not modify live FiveM resources.
- Do not edit qb-core directly.
