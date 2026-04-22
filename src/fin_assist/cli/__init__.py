"""CLI client package."""

from fin_assist.agents.metadata import AgentResult
from fin_assist.cli.client import DiscoveredAgent, HubClient
from fin_assist.cli.server import ensure_server_running

__all__ = ["AgentResult", "DiscoveredAgent", "HubClient", "ensure_server_running"]
