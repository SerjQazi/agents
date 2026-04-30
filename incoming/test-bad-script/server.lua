local ESX = exports['es_extended']:getSharedObject()

RegisterNetEvent('test-bad-script:server:takeItem', function()
    local src = source
    local player = ESX.GetPlayerFromId(src)

    if not player then
        return
    end

    local count = exports.ox_inventory:Search(src, 'count', 'lockpick')
    if count > 0 then
        exports.ox_inventory:RemoveItem(src, 'lockpick', 1)
    end

    MySQL.Async.fetchAll(
        'SELECT * FROM users WHERE identifier = @identifier',
        { ['@identifier'] = player.identifier },
        function(result)
            print(('Fake mysql-async result count: %s'):format(#result))
        end
    )
end)
