# Minimal Fix Playbook

Use this playbook to suggest the smallest safe patch for one file.

## Scope

- Inspect only the provided file contents.
- Suggest minimal fixes only.
- Do not modify the file.
- Do not produce a full rewrite unless the file is tiny and the task requires it.
- Avoid style-only changes unless they prevent confusion or bugs.
- Do not invent missing APIs or repo context.

## Output Format

Return:

1. Fix summary
2. Patch suggestion
3. Manual verification

Use unified diff style when possible:

```diff
--- a/path
+++ b/path
@@
-old line
+new line
```

If there is not enough context to suggest a safe patch, say so and list the missing context.
