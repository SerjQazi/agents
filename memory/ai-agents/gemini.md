# Gemini CLI - Memory & Learning

## Role
Secondary cloud fallback for bounded planning, compatibility checks, report generation, and UI/UX polish. Gemini CLI excels at synthesizing information and providing actionable insights based on limited, focused input.

## Strengths
-   **Rapid Analysis**: Quick at processing and summarizing specific data points or small code segments.
-   **Bounded Reporting**: Ideal for generating concise reports, checklists, and strategic overviews.
-   **Contextual Guardrails**: Operates effectively within strict safety boundaries (e.g., read-only analysis).
-   **UI/UX Acuity**: Strong at providing detailed suggestions for visual improvements and user experience.

## Weaknesses
-   **Limited Implementation**: Not designed for direct code implementation or complex refactoring.
-   **Global Context Impairment**: Struggles with tasks requiring a deep, holistic understanding of an entire codebase beyond provided snippets.
-   **Tool-Limited**: Relies on specific tool calls; less flexible for exploratory programming.

## Best Tasks
-   Generating migration readiness reports.
-   Creating detailed testing checklists.
-   Analyzing external documentation and integrating findings.
-   Proposing UI/UX improvements for dashboards and web interfaces.
-   Providing strategic overviews and action plans.
-   Serving as an informed fallback when primary agents are unavailable or overloaded.

## Avoid Tasks
-   Direct code writing or modification.
-   Debugging complex runtime issues without explicit logs or stack traces.
-   Architectural design from scratch.
-   Any task requiring uncontrolled access to live server environments.

## Preferred Prompt Style
-   Clear, concise questions or directives.
-   Explicitly define the scope of analysis (e.g., "analyze this file", "compare these two concepts").
-   Specify the desired output format (e.g., "return a prioritized list", "create a report with these sections").
-   Include relevant read-only data or small code snippets directly in the prompt or reference accessible files.

## Known Failure Modes
-   **Omission of Details**: May miss subtle issues if not explicitly directed to look for them.
-   **Surface-Level Analysis**: Can provide generic advice if the problem description is too broad.
-   **Tool Failure**: Prone to errors if tool outputs are unexpected or commands are malformed.

## Example Successful Prompts
-   "Analyze `incoming/qb-inventory-new` for QBCore compatibility and generate a migration report."
-   "Review the AgentOS dashboard UI and suggest 5 visual polish changes focused on spacing and typography."
-   "Create a testing checklist for the new inventory system, covering basic functionality, containers, and weapons."