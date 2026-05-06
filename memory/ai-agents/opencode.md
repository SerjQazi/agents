# OpenCode Agents - Memory & Learning

## Role
Specialized fallback for direct, interactive coding sessions using specific OpenRouter models. OpenCode agents are ideal for focused code generation, quick experiments, and tackling bounded coding problems when full-fledged agents (Codex, Gemini) are not the most efficient choice or are unavailable.

## Strengths
-   **Model Versatility**: Access to a wide range of OpenRouter models, allowing selection based on task (e.g., fast generation, complex reasoning, code-specific).
-   **Interactive Coding**: Designed for direct, conversational coding, making it suitable for iterative development.
-   **Focused Problem Solving**: Effective for tackling specific code challenges, generating functions, or small script segments.
-   **Cost Control**: Ability to choose models with different cost profiles for various tasks.

## Weaknesses
-   **Limited Context Window**: Model limitations on context can make large-scale codebase understanding challenging.
-   **Dependency on Human Oversight**: Requires active human guidance and context provision; less autonomous than Codex.
-   **Manual Orchestration**: Lacks inherent planning or multi-tool orchestration capabilities.

## Best Tasks
-   Generating boilerplate code for specific functions or classes.
-   Writing small utility scripts.
-   Refining existing code snippets for style or performance.
-   Converting code between different frameworks or syntaxes (e.g., ESX to QBCore functions).
-   Quickly exploring API usage or library functions.
-   Troubleshooting small, isolated code errors.

## Avoid Tasks
-   Repo-wide refactoring or architectural changes.
-   Complex bug fixes requiring deep system understanding.
-   Generating comprehensive reports or strategic plans (delegate to Gemini).
-   Tasks that require running shell commands or interacting with the file system directly (unless explicitly through a wrapper).

## Preferred Prompt Style
-   Direct, specific coding requests.
-   Provide relevant code snippets, desired output format, and constraints.
-   Break down complex problems into smaller, manageable sub-tasks.
-   Explicitly state the desired programming language, framework, or library.

## Known Failure Modes
-   **Outdated Information**: Models might generate code based on outdated documentation or common patterns if not provided with current context.
-   **Over-simplification**: May miss edge cases or subtle requirements without explicit instructions.
-   **Repetitive Suggestions**: Can get stuck in loops or repeat previous responses if the conversation isn't steered effectively.

## Example Successful Prompts
-   "Write a Lua function to convert an ESX `RegisterNetEvent` to a QBCore `RegisterNetEvent` with appropriate callbacks."
-   "Generate a React functional component for a simple file upload input, including drag-and-drop functionality."
-   "Refactor this Python code snippet to use list comprehensions for improved readability and conciseness."
-   "Given this `fxmanifest.lua`, what are the minimal changes to add `ox_lib` as a dependency?"