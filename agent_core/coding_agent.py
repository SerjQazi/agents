"""Coding agent that returns planning guidance only."""


class CodingAgent:
    name = "coding_agent"
    description = "Creates coding plans without editing files."

    def handle(self, message: str = "") -> dict:
        topic = message.strip() or "the requested coding task"
        plan = [
            "Clarify the expected behavior and constraints.",
            "Inspect the relevant files and existing patterns.",
            "Identify the smallest safe implementation path.",
            "List tests or manual checks needed before changing code.",
            "Only edit files after explicit approval in a separate workflow.",
        ]

        return {
            "agent": self.name,
            "response": f"Planning response for: {topic}",
            "plan": plan,
            "edits_performed": False,
        }
