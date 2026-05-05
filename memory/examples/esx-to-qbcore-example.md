# ESX to QBCore Example

## Input Task

Review `server.lua` for ESX calls and suggest QBCore replacements.

## Good Output Shape

Compatibility summary:
The file uses ESX player lookup, money access, and server callbacks. These can be converted locally, but money behavior should be reviewed because account names and audit reasons matter.

ESX references found:

- `ESX.GetPlayerFromId(source)`
- `xPlayer.getMoney()`
- `xPlayer.removeMoney(price)`
- `ESX.RegisterServerCallback(...)`

Suggested replacements:

```lua
local QBCore = exports['qb-core']:GetCoreObject()
local Player = QBCore.Functions.GetPlayer(source)
local cash = Player.Functions.GetMoney('cash')
Player.Functions.RemoveMoney('cash', price, 'resource-action')
QBCore.Functions.CreateCallback('resource:callback', function(source, cb)
    -- callback body
end)
```

Risk notes:
Confirm whether the ESX money source should map to `cash` or `bank`. Do not apply automatically if the script touches inventory, player identity, or database persistence.
