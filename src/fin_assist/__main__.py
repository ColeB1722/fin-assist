"""Entry point for fin-assist CLI."""

from fin_assist.config.loader import load_config
from fin_assist.credentials.store import CredentialStore
from fin_assist.ui.app import FinAssistApp


def main() -> None:
    """Main entry point for the application."""
    config = load_config()
    credentials = CredentialStore()
    app = FinAssistApp(config=config, credentials=credentials)
    app.run()


if __name__ == "__main__":
    main()
