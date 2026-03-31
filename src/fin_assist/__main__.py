"""CLI entry point for fin-assist.

Commands
--------
fin-assist agents                 List available agents.
fin-assist do <agent> <prompt>    One-shot query (no memory).
fin-assist talk <agent>           Multi-turn chat session.
fin-assist serve                  Start the agent hub server.
"""

from __future__ import annotations

import sys

from fin_assist.cli.main import main as cli_main

main = cli_main


if __name__ == "__main__":
    sys.exit(cli_main())
