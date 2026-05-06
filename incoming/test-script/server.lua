local ESX = exports['es_extended']:getSharedObject()

RegisterNetEvent('test:payPlayer', function()
    local src = source
    local xPlayer = ESX.GetPlayerFromId(src)
    xPlayer.addMoney(500)
end)
