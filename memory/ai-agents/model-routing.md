# Model Routing for AgentOS

This document provides guidelines for selecting the appropriate AI model or agent based on the task at hand. Effective model routing maximizes efficiency, leverages specialized strengths, and minimizes operational costs.

## Primary Agent: Codex

-   **Description**: The flagship AI for heavy engineering tasks.
-   **Best For**: Implementing new features, complex bug fixes, large-scale refactoring, architectural analysis, generating comprehensive test suites, and driving multi-step project tasks autonomously.
-   **When to Use**: When a task requires deep code understanding, significant code modification, and adherence to complex engineering standards.
-   **Avoid For**: Quick questions, simple summarization, or very rapid prototyping.

## Secondary Fallback: Gemini CLI

-   **Description**: A cloud-based agent for planning, reporting, and focused analysis.
-   **Best For**: Generating strategic plans, migration readiness reports, testing checklists, UI/UX polish suggestions, and acting as an informed, read-only advisor.
-   **When to Use**: When you need high-quality analysis, structured reports, or a second opinion without direct code modification. Also excellent for synthesizing information from bounded contexts.
-   **Avoid For**: Any direct code implementation, debugging runtime issues without specific logs, or tasks requiring deep interaction with the codebase's internal structure.

## Night-Shift / Specialized Fallback: OpenCode + OpenRouter Models

-   **Description**: A suite of specialized models accessible via `opencode-` launchers for interactive, focused coding sessions.
-   **Best For**:
    -   **`opencode-sonnet` / `opencode-claude` (Claude Sonnet/3.7 Sonnet)**: General coding, complex reasoning, detailed code reviews, and UI-focused work.
    -   **`opencode-haiku` (Claude Haiku)**: Fast, lightweight code generation, quick checks, minor bug fixes, and rapid prototyping.
    -   **`opencode-gemini-pro` (Gemini 2.5 Pro)**: Strong multi-modal tasks, complex refactoring, and general coding where advanced reasoning is beneficial.
    -   **`opencode-gemini` (Gemini 2.5 Flash)**: Very fast and cost-effective for UI generation, quick analysis, and initial diagnosis.
    -   **`opencode-deepseek` (DeepSeek Coder)**: Highly specialized for generating idiomatic code snippets and focused refactoring (if available).
-   **When to Use**: When Codex is unavailable, for specific, bounded coding tasks, or when a model's unique strengths (e.g., speed, coding prowess) are specifically required. Ideal for exploring solutions interactively.
-   **Avoid For**: Tasks requiring large-scale planning or reporting (delegate to Gemini CLI), or autonomous multi-step execution across the codebase (delegate to Codex).

## Internal AgentOS Agents (`planner_agent`, `coding_agent`, `builder_agent`)

-   **Description**: Autonomous agents within the AgentOS pipeline for specific phases of script integration.
-   **Planner Agent**: Performs initial scans, framework detection, dependency analysis, risk assessment, and generates a plan.
-   **Coding Agent**: Applies automated fixes based on the plan, generates staged code changes, and creates human-reviewable reports.
-   **Builder Agent**: Orchestrates the entire build process, including planning, coding, and deployment validation.
-   **When to Use**: These agents operate autonomously within the AgentOS dashboard workflow for script intake, staging, and review.

## Local Ollama (Emergency-Only)

-   **Description**: Local large language models running on the AgentOS VM.
-   **When to Use**: **Only as a last resort** when all other cloud-based models are completely unavailable and a task is extremely small and critical. This VM is CPU-only with limited resources, making local LLMs very slow and resource-intensive.
-   **Avoid For**: Any regular or complex task. Performance is severely degraded, leading to inefficient workflows.

---

**General Principle**: Always use the highest-reasoning and most appropriate agent for the task. Fallback agents should only be used when necessary, with a clear understanding of their strengths and limitations. Documentation (`memory/ai-agents/*.md`) should be consulted for specific use cases.
