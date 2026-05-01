local ESX = exports['es_extended']:getSharedObject()

CreateThread(function()
    exports.ox_target:addBoxZone({
        coords = vec3(0.0, 0.0, 72.0),
        size = vec3(1.5, 1.5, 2.0),
        rotation = 0.0,
        options = {
            {
                name = 'test_bad_script_open',
                icon = 'fa-solid fa-box',
                label = 'Open broken stash',
                onSelect = function()
                    ESX.ShowNotification('This fake resource expects ESX and ox_target.')
                    exports.ox_inventory:openInventory('stash', 'test_bad_script')
                end
            }
        }
    })
end)
