# Codex Prompt: Pappu Inventory Staging & Preparation

## Context
We are preparing to migrate from our current inventory system to the **Pappu Inventory (NP 4.0 Style)**. 
Source: `/home/agentzero/agents/incoming/qb-inventory-new`
Target: `/home/agentzero/agents/staging/pappu-inventorynp`

## Directives
1. **Source Preparation**:
   - Copy all files from `incoming/qb-inventory-new` to `staging/pappu-inventorynp`.
   - Ensure the folder name in `staging` is exactly `pappu-inventorynp`.

2. **Configuration**:
   - In `staging/pappu-inventorynp/config.lua`:
     - Set `Config.Framework = "qbcore"`.
     - Set `Config.QBCoreVersion = "new"`.
     - Verify weight and slot limits match our current server standards (Default: 120kg / 15 slots).

3. **Manifest Integrity**:
   - Ensure `fxmanifest.lua` points correctly to all scripts and files.
   - Check the `@qb-weapons/config.lua` dependency. If the live server uses a different path, note it in a staging report.

4. **Safety Audit (CRITICAL)**:
   - Inspect `HPX-inventory.sql`. 
   - **DO NOT** run this SQL.
   - Identify that the `player_vehicles` table definition in the SQL should be DISCARDED during live migration to prevent data loss.
   - Create a `staging/pappu-inventorynp/MIGRATION_SQL.sql` containing ONLY the `CREATE TABLE IF NOT EXISTS` for `stashitems`, `trunkitems`, and `gloveboxitems`.

5. **Resource Bridge**:
   - If the current server uses `ps-inventory`, create a `staging/pappu-inventorynp/PS_COMPAT.lua` (server-side) that aliases any unique `ps-inventory` exports to the new ones.

6. **Image Sync**:
   - Note: We will need to sync icons from the old inventory's `html/images` to this one later. For now, just identify if there are missing essential icons in `html/images/`.

## Output
- A fully prepared `staging/pappu-inventorynp` resource.
- A `reports/staging-readiness.md` summarizing any manual tweaks made during the copy.
- A `migration-warnings.txt` for the final human reviewer.

**SAFETY RULE**: Do not touch `/home/agentzero/fivem-server` or any live resources. Work ONLY in `staging/`.
