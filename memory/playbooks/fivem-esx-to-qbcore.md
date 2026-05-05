# FiveM ESX to QBCore Playbook

Use this playbook for narrow review or patch-planning tasks on a single FiveM script file that appears to use ESX APIs and needs QBCore-compatible guidance.

## Scope

- Inspect only the target file provided in the prompt.
- Produce a report or patch suggestion only.
- Do not assume access to the full resource unless file contents are included.
- Do not edit `qb-core`.
- Do not change inventory, money, permissions, database schema, or player data behavior without flagging it for human review.

## Conversion Map

- `ESX = nil` and `TriggerEvent('esx:getSharedObject', ...)` usually become `local QBCore = exports['qb-core']:GetCoreObject()`.
- `ESX.GetPlayerFromId(source)` usually becomes `QBCore.Functions.GetPlayer(source)`.
- `xPlayer.identifier` usually maps to `Player.PlayerData.citizenid` or `Player.PlayerData.license` depending on persistence requirements.
- `xPlayer.getMoney()` usually maps to `Player.Functions.GetMoney('cash')`.
- `xPlayer.addMoney(amount)` usually maps to `Player.Functions.AddMoney('cash', amount, reason)`.
- `xPlayer.removeMoney(amount)` usually maps to `Player.Functions.RemoveMoney('cash', amount, reason)`.
- `xPlayer.getAccount('bank').money` usually maps to `Player.Functions.GetMoney('bank')`.
- `xPlayer.addAccountMoney('bank', amount)` usually maps to `Player.Functions.AddMoney('bank', amount, reason)`.
- `xPlayer.removeAccountMoney('bank', amount)` usually maps to `Player.Functions.RemoveMoney('bank', amount, reason)`.
- `xPlayer.job.name` usually maps to `Player.PlayerData.job.name`.
- `xPlayer.job.grade` usually maps to `Player.PlayerData.job.grade.level`.
- `ESX.RegisterServerCallback(name, fn)` usually becomes `QBCore.Functions.CreateCallback(name, fn)`.
- `ESX.TriggerServerCallback` on clients usually becomes `QBCore.Functions.TriggerCallback`.
- `ESX.ShowNotification(msg)` usually becomes `QBCore.Functions.Notify(msg, type)`.
- `esx:playerLoaded` usually maps to `QBCore:Client:OnPlayerLoaded`.
- `esx:setJob` usually maps to `QBCore:Client:OnJobUpdate`.

## Output Format

Return:

1. Compatibility summary.
2. ESX references found.
3. Suggested QBCore replacements.
4. Risk notes requiring human/Codex review.
5. A concise patch-style snippet if the change is safe and local.

Do not return a complete rewritten resource unless explicitly asked.
