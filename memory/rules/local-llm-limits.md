# Local LLM Limits

- The local model is a fallback worker, not the primary engineer.
- Assume the model cannot understand the whole repository.
- Give it one file, one playbook, and one narrow task.
- Ask for reports, checklists, and patch suggestions rather than direct edits.
- Prefer small deterministic tasks: classify, identify references, suggest replacements, summarize risks.
- Avoid broad tasks: redesign the system, refactor multiple modules, infer hidden architecture, or make production decisions.
- Review local model output before applying it.
- When output is vague, retry with a narrower task and a smaller file.
