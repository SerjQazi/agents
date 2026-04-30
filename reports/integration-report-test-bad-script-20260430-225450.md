# FiveM Integration Report

Generated: 2026-04-30T22:54:50
Script: `/home/agentzero/agents/incoming/test-bad-script`
Server: `/home/agentzero/fivem-server/txData/QBCore_F16AC8.base`

## Script Summary

- Manifest present at script root: yes
- Files scanned: 3

## Detected Script Assumptions
- framework: ESX
- inventory: ox_inventory
- target: ox_target
- database: mysql-async

## Evidence
- framework/ESX: ESX.GetPlayerFromId, es_extended, getSharedObject
- inventory/ox_inventory: exports.ox_inventory, ox_inventory
- target/ox_target: exports.ox_target, ox_target
- database/mysql-async: MySQL.Async, mysql-async

## Server Compatibility
- qb-core: present
- qb-inventory: present
- qb-target: present
- qb-menu: present
- qb-input: present
- oxmysql: present
- ox_lib: missing
- illenium-appearance: missing
- pma-voice: present

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

## Safety Gates

- Stop and ask before database schema changes.
- Stop and ask before inventory core changes.
- Stop and ask before money, permissions, or player data changes.
- Prefer adapters inside the incoming script over server core edits.

## File List
- client.lua
- fxmanifest.lua
- server.lua
