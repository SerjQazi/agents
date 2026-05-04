"""Compatibility entrypoint for the Bubbles Agent."""

from bots.bubbles_agent.app import *  # noqa: F401,F403
from bots.bubbles_agent.app import main


if __name__ == "__main__":
    main()
