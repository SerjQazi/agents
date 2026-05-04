-- AGENT FIX START
-- Mapped local ESX = exports['es_extended']:getSharedObject() to local QBCore = exports['qb-core']:GetCoreObject().
-- Mapped ESX.ShowNotification to QBCore.Functions.Notify.
-- Mapped exports.ox_target to exports['qb-target'].
-- Mapped ox_target to qb-target.
-- AGENT FIX END
local QBCore = exports['qb-core']:GetCoreObject()

CreateThread(function()
    exports['qb-target']:addBoxZone({
        coords = vec3(0.0, 0.0, 72.0),
        size = vec3(1.5, 1.5, 2.0),
        rotation = 0.0,
        options = {
            {
                name = 'test_bad_script_open',
                icon = 'fa-solid fa-box',
                label = 'Open broken stash',
                onSelect = function()
                    QBCore.Functions.Notify('This fake resource expects ESX and qb-target.')
                    exports.ox_inventory:openInventory('stash', 'test_bad_script')
                end
            }
        }
    })
end)
