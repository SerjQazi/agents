# Upload Pipeline Debug Playbook

Use this playbook for a narrow diagnostic pass on one script, log excerpt, or configuration file related to upload, staging, deployment, or server sync.

## Scope

- Inspect only the provided target file contents.
- Identify likely failure points and commands to verify them.
- Do not restart services.
- Do not push to Git.
- Do not delete files.
- Do not assume remote access unless the prompt includes it.

## Checklist

- Confirm source path, destination path, and working directory assumptions.
- Check whether ignored files, `.env` files, virtualenvs, build artifacts, or secrets could be included accidentally.
- Check script permissions and shebangs for executable scripts.
- Check missing directories before copy/sync operations.
- Check whether commands rely on environment variables that may not exist in non-interactive shells.
- Check whether relative paths depend on a specific launch directory.
- Check whether the pipeline reports errors but continues due to `|| true`, missing `set -e`, or swallowed exit codes.
- Check for timestamped reports or logs that can confirm the last successful operation.

## Output Format

Return:

1. Most likely cause.
2. Evidence from the file.
3. Minimal verification commands.
4. Suggested small fix.
5. Risks or unknowns.

Keep the answer focused on one file and one failure mode unless the evidence clearly points to several.
