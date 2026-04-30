fx_version 'cerulean'
game 'gta5'

description 'Fake broken test resource for the FiveM integration agent'

shared_script 'config.lua'

client_script 'client.lua'
server_script 'server.lua'

dependencies {
    'es_extended',
    'ox_inventory',
    'ox_target',
    'mysql-async'
}
