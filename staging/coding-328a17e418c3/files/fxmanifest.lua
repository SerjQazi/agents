-- AGENT FIX START
-- Mapped mysql-async to oxmysql.
-- Mapped ox_target to qb-target.
-- AGENT FIX END
fx_version 'cerulean'
game 'gta5'

description 'Fake broken test resource for the FiveM integration agent'

shared_script 'config.lua'

client_script 'client.lua'
server_script 'server.lua'

dependencies {
    'es_extended',
    'ox_inventory',
    'qb-target',
    'oxmysql'
}
