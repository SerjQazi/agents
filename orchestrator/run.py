#!/usr/bin/env python3
"""AgentOS Orchestrator - Main entry point."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestrator.cli import main

if __name__ == "__main__":
    sys.exit(main())