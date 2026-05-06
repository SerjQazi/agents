# Codex Agent - Memory & Learning

## Role
Primary AI agent for heavy implementation, complex problem-solving, repo-wide analysis, feature development, and test repair. Codex is designed for robust, multi-step engineering tasks.

## Strengths
-   **Deep Contextual Understanding**: Excellent at understanding large codebases and complex architectural patterns.
-   **Robust Implementation**: Capable of generating and modifying significant code sections, including tests.
-   **Problem Reproduction**: Strong ability to reproduce reported issues and formulate empirical test cases.
-   **Architectural Alignment**: Adheres to existing code conventions and architectural patterns.

## Weaknesses
-   **Cost-Intensive**: High token usage can lead to higher operational costs.
-   **Latency**: Can be slower for quick, iterative feedback loops due to its thoroughness.
-   **Boundedness**: Less effective at tasks requiring broad, open-ended ideation without specific constraints.

## Best Tasks
-   Implementing new features.
-   Fixing complex bugs that require code modification across multiple files.
-   Refactoring large code sections.
-   Generating and updating test suites.
-   Architectural analysis and proposing system-wide changes.
-   Complex script integration and migration efforts.

## Avoid Tasks
-   Simple, quick questions that can be answered with a direct search or a smaller model.
-   Brainstorming or highly speculative research without a clear deliverable.
-   Tasks with extremely tight latency requirements.

## Preferred Prompt Style
-   Clear, detailed directives with explicit goals and constraints.
-   Provide all relevant context, including file paths, error messages, and expected outcomes.
-   Emphasize safety, idempotence, and adherence to engineering standards.
-   When fixing bugs, always include reproduction steps and expected fix verification.

## Known Failure Modes
-   **Hallucination of APIs/Functions**: May invent non-existent functions or methods if context is ambiguous or incomplete.
-   **Over-Engineering**: Can sometimes propose overly complex solutions for simpler problems.
-   **Scope Creep**: Without strict directives, may expand beyond the immediate task.
-   **Incomplete Validation**: May overlook edge cases if testing instructions are not exhaustive.

## Example Successful Prompts
-   "Implement user authentication using OAuth 2.0. Modify `auth.py`, `models.py`, and create `tests/test_auth.py`."
-   "Fix the race condition in `tokenizer.c` by implementing a mutex. Reproduce with `test_tokenizer.py` before and after."
-   "Refactor the `OrderProcessor` class in `services/order.py` to use a strategy pattern. Ensure backward compatibility and update `OrderService`."