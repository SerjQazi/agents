-- AGENT FIX START
-- Mapped local ESX = exports['es_extended']:getSharedObject() to local QBCore = exports['qb-core']:GetCoreObject().
-- Mapped ESX.GetPlayerFromId to QBCore.Functions.GetPlayer.
-- Mapped player.identifier to player.PlayerData.citizenid.
-- Mapped mysql-async to oxmysql.
-- Mapped MySQL.Async to MySQL.
-- AGENT FIX END
local QBCore = exports['qb-core']:GetCoreObject()

RegisterNetEvent('test-bad-script:server:takeItem', function()
    local src = source
    local player = QBCore.Functions.GetPlayer(src)

    if not player then
        return
    end

    local count = exports.ox_inventory:Search(src, 'count', 'lockpick')
    if count > 0 then
        exports.ox_inventory:RemoveItem(src, 'lockpick', 1)
    end

    MySQL.fetchAll(
        'SELECT * FROM users WHERE identifier = @identifier',
        { ['@identifier'] = player.PlayerData.citizenid },
        function(result)
            print(('Fake oxmysql result count: %s'):format(#result))
        end
    )
end)
