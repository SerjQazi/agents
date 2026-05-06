# FiveM Script Integration Checklist

Use this playbook to produce a short integration checklist for one incoming or staged FiveM resource folder.

## Scope

- Review the folder summary only.
- Do not request full repository context.
- Do not modify files.
- Do not push to Git.
- Do not restart services.
- Do not modify live FiveM resources directly.
- Produce staging-only recommendations.

## Identify Framework

Classify the resource as one or more of:

- ESX: `ESX`, `es_extended`, `esx:getSharedObject`, `esx:` events.
- QBCore: `QBCore`, `qb-core`, `QBCore.Functions`, `qb-` resources.
- Qbox: `qbx_core`, `qbx_`, `exports.qbx_core`.
- Standalone: no framework-specific player, job, money, inventory, callback, or notification APIs found.

If the summary is inconclusive, say so.

## Identify Dependencies

Look for declared or implied dependencies:

- `ox_lib`
- `ox_inventory`
- `qb-inventory`
- `qb-target`
- `ox_target`
- `mysql-async`
- `oxmysql`
- framework resources such as `qb-core`, `qbx_core`, `es_extended`

Flag mismatches, such as ESX APIs inside a QBCore resource or both `qb-target` and `ox_target` assumptions.

## Identify Important Files

Call out:

- Manifest files: `fxmanifest.lua`, `__resource.lua`.
- SQL files: `*.sql`.
- Config files: names containing `config`, or common config JSON/Lua files.
- Client files: paths or names containing `client`.
- Server files: paths or names containing `server`.
- Shared files: paths or names containing `shared`, `config`, or `locale`.
- UI files: `html`, `css`, `js`, `json`.

## Risk Review

Risky edits include:

- Database schema or SQL migration changes.
- Inventory core changes.
- Money/account changes.
- Permissions/group/admin changes.
- Player identity, citizen ID, license, job, gang, metadata, or saved state changes.
- Direct edits to `qb-core`, `qbx_core`, `es_extended`, live server resources, or shared framework files.
- Replacing target/inventory/mysql systems without an adapter plan.
- Running SQL automatically.

## Safe Integration Process

Recommend this staged workflow:

1. Scan the incoming resource folder.
2. Identify framework, dependencies, SQL, config, and client/server/shared split.
3. Create a compatibility plan.
4. Stage changes in `~/agents/staging` or another staging-only folder.
5. Keep adapters inside the incoming/staged resource when possible.
6. Back up before applying to any live resource.
7. Review staged changes manually or with Codex.
8. Apply only reviewed changes.
9. Push to Git only after human/Codex review and secret checks.

## Output Format

Return only:

1. Framework guess.
2. Dependencies found.
3. Important files.
4. Risk flags.
5. Staging-only recommendations.

Keep the report short and specific to the provided folder summary.
