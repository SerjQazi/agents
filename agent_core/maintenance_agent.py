"""Maintenance agent that suggests commands without executing them."""


class MaintenanceAgent:
    name = "maintenance_agent"
    description = "Suggests safe maintenance checks and commands."

    def handle(self, message: str = "") -> dict:
        commands = [
            {
                "purpose": "Review available package updates",
                "command": "sudo apt update && apt list --upgradable",
            },
            {
                "purpose": "Check disk usage",
                "command": "df -h",
            },
            {
                "purpose": "Inspect largest journal logs",
                "command": "journalctl --disk-usage",
            },
            {
                "purpose": "View failed systemd services",
                "command": "systemctl --failed",
            },
            {
                "purpose": "Review recent boot errors",
                "command": "journalctl -p err -b",
            },
        ]

        return {
            "agent": self.name,
            "response": "Suggested maintenance commands only. Nothing was executed.",
            "commands": commands,
            "note": "Review each command before running it manually on the server.",
        }
