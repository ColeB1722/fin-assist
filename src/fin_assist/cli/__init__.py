"""CLI client package."""

from fin_assist.cli.client import A2AClient, AgentResult, DiscoveredAgent
from fin_assist.cli.server import ensure_server_running

__all__ = ["A2AClient", "AgentResult", "DiscoveredAgent", "ensure_server_running"]
