from __future__ import annotations

import argparse

from fin_assist.hub import create_hub_app


def main() -> None:
    parser = argparse.ArgumentParser(prog="fin-assist")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("serve")
    args = parser.parse_args()

    if args.command == "serve":
        create_hub_app()
        print("fin-assist hub ready")
        return

    parser.print_help()


if __name__ == "__main__":
    main()
