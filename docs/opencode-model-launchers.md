# OpenCode Model Launchers for AgentOS

This document outlines the specialized `opencode-` launcher commands available for interacting with various OpenRouter models within the AgentOS environment. These launchers streamline the process of initiating OpenCode sessions with predefined models, providing quick access for different coding and analysis tasks.

**Important Context:**

*   **Codex remains Primary**: For most software engineering tasks, Codex is the primary, high-reasoning agent.
*   **Gemini CLI is Fallback**: Gemini CLI serves as the cloud fallback for bounded planning and repo-wide analysis.
*   **OpenCode + OpenRouter is Night-Shift Coding Fallback**: These OpenCode launchers provide a powerful "night-shift" fallback, offering direct access to advanced models via OpenRouter for situations where Codex might be unavailable or a different model's strengths are desired.

## Available Launchers

The following commands are symlinked into `/home/agentzero/.local/bin/` for easy execution from your shell:

*   `opencode-models`: Lists recommended OpenCode/OpenRouter models, their use cases, and cost/risk notes.
*   `opencode-sonnet`: Launches OpenCode with `openrouter/anthropic/claude-sonnet-4.5`.
*   `opencode-claude`: Launches OpenCode with `openrouter/anthropic/claude-3.7-sonnet`.
*   `opencode-haiku`: Launches OpenCode with `openrouter/anthropic/claude-3.5-haiku`.
*   `opencode-gemini-pro`: Launches OpenCode with `openrouter/google/gemini-2.5-pro`.
*   `opencode-gemini`: Launches OpenCode with `openrouter/google/gemini-2.5-flash`.

## When to Use Which Model

| Command Alias             | Full Model Name                             | Recommended Use Case                                                                                                    | Cost/Risk Note                  |
| :------------------------ | :------------------------------------------ | :---------------------------------------------------------------------------------------------------------------------- | :------------------------------ |
| `opencode-sonnet`         | `openrouter/anthropic/claude-sonnet-4.5`    | General coding, complex reasoning, UI work, detailed analysis of code structure.                                        | Medium cost, balanced risk      |
| `opencode-claude`         | `openrouter/anthropic/claude-3.7-sonnet`    | General coding, task planning, comprehensive code reviews (as a fallback to Codex), and architectural discussions.      | Medium cost, balanced risk      |
| `opencode-haiku`          | `openrouter/anthropic/claude-3.5-haiku`     | Fast, lightweight coding, quick checks, minor bug fixes, script generation, and rapid prototyping.                      | Low cost, low risk              |
| `opencode-gemini-pro`     | `openrouter/google/gemini-2.5-pro`          | Strong multi-modal capabilities, general coding, complex refactoring, and tasks requiring deep pattern recognition.   | Medium cost, balanced risk      |
| `opencode-gemini`         | `openrouter/google/gemini-2.5-flash`        | Fast, lightweight code generation, UI component generation, quick analysis of logs, and initial problem diagnosis.      | Low cost, low risk              |
| `opencode-gemini-pro-preview` | `openrouter/google/gemini-1.5-pro-preview` | Advanced reasoning, very large context window, experimental features (use with caution if available).                   | High cost, high risk            |
| `opencode-deepseek`       | `openrouter/deepseek/deepseek-coder-v2`     | Highly specialized for coding tasks, excellent for generating idiomatic code snippets and refactoring (if available). | Low cost, focused               |

**Important Considerations:**

*   **Inventory Migration**: For critical tasks like inventory migration, it is still highly recommended to wait for Codex high-reasoning, as it is specifically tuned for our FiveM resource context. The `opencode-` launchers are best for exploratory coding or non-critical tasks.
*   **UI Work**: For UI-related coding, `opencode-gemini` (Flash) or `opencode-sonnet` are often good choices due to their strong performance in generating HTML/CSS/JS.

## Safety Reminder

When using any `opencode-` launcher:

> **Work inside `/home/agentzero/agents`. Do not touch live FiveM resources (e.g., `/home/agentzero/fivem-server`) unless explicitly approved by a human.**

Always verify the actions proposed by the model and operate within the staging environment (`/home/agentzero/agents/staging`) for any resource modifications.
