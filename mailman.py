"""Compatibility entrypoint for the Mail Agent."""

from bots.mail_agent.app import *  # noqa: F401,F403
from bots.mail_agent.app import main


if __name__ == "__main__":
    main()
