"""Tests for cli/main.py — CLI command dispatch.

Strategy: `main()` calls `asyncio.run()` for async commands. In tests we patch
`asyncio.run` to execute the coroutine synchronously via
`asyncio.get_event_loop().run_until_complete()`, avoiding the "cannot be called
from a running event loop" error that occurs in pytest-asyncio contexts.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fin_assist.agents.base import AgentCardMeta
from fin_assist.cli.client import AgentResult, DiscoveredAgent
from fin_assist.cli.main import main

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _patch_asyncio_run():
    """Patch asyncio.run to use run_until_complete, so tests can be sync."""
    loop = asyncio.new_event_loop()

    def fake_run(coro):
        return loop.run_until_complete(coro)

    return patch("fin_assist.cli.main.asyncio.run", side_effect=fake_run)


def _run_main(*argv: str) -> int:
    return main(list(argv))


def _make_discovered(
    name: str = "shell",
    requires_approval: bool = False,
    supports_regenerate: bool = False,
) -> DiscoveredAgent:
    return DiscoveredAgent(
        name=name,
        description="test agent",
        url=f"http://localhost/agents/{name}/",
        card_meta=AgentCardMeta(
            requires_approval=requires_approval,
            supports_regenerate=supports_regenerate,
        ),
    )


def _mock_client(
    agents: list[DiscoveredAgent] | None = None,
    run_result: AgentResult | None = None,
    run_error: Exception | None = None,
) -> AsyncMock:
    client = AsyncMock()
    client.discover_agents = AsyncMock(return_value=agents or [])
    client.close = AsyncMock()
    if run_error:
        client.run_agent = AsyncMock(side_effect=run_error)
    else:
        client.run_agent = AsyncMock(
            return_value=run_result or AgentResult(success=True, output="")
        )
    return client


# ---------------------------------------------------------------------------
# `serve` command (synchronous — no asyncio.run)
# ---------------------------------------------------------------------------


class TestServeCommand:
    def test_serve_starts_uvicorn(self):
        with (
            patch("fin_assist.cli.main.create_hub_app", return_value=MagicMock()),
            patch("fin_assist.cli.main.uvicorn.run") as mock_uvicorn,
        ):
            result = _run_main("serve")

        mock_uvicorn.assert_called_once()
        assert result == 0

    def test_serve_allows_host_override(self):
        with (
            patch("fin_assist.cli.main.create_hub_app", return_value=MagicMock()),
            patch("fin_assist.cli.main.uvicorn.run") as mock_uvicorn,
        ):
            _run_main("serve", "--host", "0.0.0.0")

        call_kwargs = mock_uvicorn.call_args
        host_used = call_kwargs.kwargs.get("host") or call_kwargs.args[1]
        assert host_used == "0.0.0.0"

    def test_serve_allows_port_override(self):
        with (
            patch("fin_assist.cli.main.create_hub_app", return_value=MagicMock()),
            patch("fin_assist.cli.main.uvicorn.run") as mock_uvicorn,
        ):
            _run_main("serve", "--port", "8080")

        call_kwargs = mock_uvicorn.call_args
        port_used = call_kwargs.kwargs.get("port") or call_kwargs.args[2]
        assert port_used == 8080


# ---------------------------------------------------------------------------
# _hub_client context manager
# ---------------------------------------------------------------------------


class TestHubClient:
    """Tests for the _hub_client async context manager directly."""

    async def test_yields_connected_client(self):
        from fin_assist.cli.main import _hub_client

        with (
            patch(
                "fin_assist.cli.main.ensure_server_running",
                new_callable=AsyncMock,
                return_value="http://localhost:4096",
            ),
            patch("fin_assist.cli.main.HubClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.close = AsyncMock()
            mock_cls.return_value = mock_client

            async with _hub_client(MagicMock()) as client:
                assert client is mock_client

    async def test_closes_client_on_clean_exit(self):
        from fin_assist.cli.main import _hub_client

        with (
            patch(
                "fin_assist.cli.main.ensure_server_running",
                new_callable=AsyncMock,
                return_value="http://localhost:4096",
            ),
            patch("fin_assist.cli.main.HubClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.close = AsyncMock()
            mock_cls.return_value = mock_client

            async with _hub_client(MagicMock()):
                pass

        mock_client.close.assert_called_once()

    async def test_closes_client_and_reraises_on_runtime_error(self):
        from fin_assist.cli.main import _hub_client

        with (
            patch(
                "fin_assist.cli.main.ensure_server_running",
                new_callable=AsyncMock,
                return_value="http://localhost:4096",
            ),
            patch("fin_assist.cli.main.HubClient") as mock_cls,
            patch("fin_assist.cli.main.render_error"),
        ):
            mock_client = AsyncMock()
            mock_client.close = AsyncMock()
            mock_cls.return_value = mock_client

            with pytest.raises(ValueError):
                async with _hub_client(MagicMock()):
                    raise ValueError("boom")

        mock_client.close.assert_called_once()

    async def test_renders_error_on_runtime_exception(self):
        from fin_assist.cli.main import _hub_client

        rendered = []

        with (
            patch(
                "fin_assist.cli.main.ensure_server_running",
                new_callable=AsyncMock,
                return_value="http://localhost:4096",
            ),
            patch("fin_assist.cli.main.HubClient") as mock_cls,
            patch("fin_assist.cli.main.render_error", side_effect=rendered.append),
        ):
            mock_client = AsyncMock()
            mock_client.close = AsyncMock()
            mock_cls.return_value = mock_client

            with pytest.raises(RuntimeError):
                async with _hub_client(MagicMock()):
                    raise RuntimeError("network gone")

        assert any("network gone" in str(m) for m in rendered)

    async def test_renders_error_and_reraises_on_startup_failure(self):
        from fin_assist.cli.main import _hub_client
        from fin_assist.cli.server import ServerStartupError

        rendered = []

        with (
            patch(
                "fin_assist.cli.main.ensure_server_running",
                new_callable=AsyncMock,
                side_effect=ServerStartupError("port in use"),
            ),
            patch("fin_assist.cli.main.render_error", side_effect=rendered.append),
        ):
            with pytest.raises(ServerStartupError):
                async with _hub_client(MagicMock()):
                    pass  # never reached

        assert any("port in use" in str(m) for m in rendered)


# ---------------------------------------------------------------------------
# `agents` command
# ---------------------------------------------------------------------------


class TestAgentsCommand:
    def test_agents_calls_discover_agents(self):
        mock_client = _mock_client(agents=[])

        with (
            _patch_asyncio_run(),
            patch(
                "fin_assist.cli.main.ensure_server_running",
                new_callable=AsyncMock,
                return_value="http://localhost:4096",
            ),
            patch("fin_assist.cli.main.HubClient", return_value=mock_client),
            patch("fin_assist.cli.main.render_agents_list"),
        ):
            result = _run_main("agents")

        assert result == 0
        mock_client.discover_agents.assert_called_once()

    def test_agents_returns_1_on_server_startup_error(self):
        from fin_assist.cli.server import ServerStartupError

        with (
            _patch_asyncio_run(),
            patch(
                "fin_assist.cli.main.ensure_server_running",
                new_callable=AsyncMock,
                side_effect=ServerStartupError("can't start"),
            ),
            patch("fin_assist.cli.main.render_error"),
        ):
            result = _run_main("agents")

        assert result == 1


# ---------------------------------------------------------------------------
# `do` command — non-approval path
# ---------------------------------------------------------------------------


class TestDoCommandNoApproval:
    def test_discovers_agent_before_running(self):
        agent = _make_discovered("shell", requires_approval=False)
        mock_client = _mock_client(
            agents=[agent],
            run_result=AgentResult(success=True, output="ls -la"),
        )

        with (
            _patch_asyncio_run(),
            patch(
                "fin_assist.cli.main.ensure_server_running",
                new_callable=AsyncMock,
                return_value="http://localhost:4096",
            ),
            patch("fin_assist.cli.main.HubClient", return_value=mock_client),
            patch("fin_assist.cli.main.render_response"),
        ):
            result = _run_main("do", "shell", "list files")

        assert result == 0
        assert mock_client.discover_agents.call_count >= 1
        mock_client.run_agent.assert_called_once_with("shell", "list files")

    def test_returns_1_for_unknown_agent(self):
        mock_client = _mock_client(agents=[_make_discovered("default")])

        with (
            _patch_asyncio_run(),
            patch(
                "fin_assist.cli.main.ensure_server_running",
                new_callable=AsyncMock,
                return_value="http://localhost:4096",
            ),
            patch("fin_assist.cli.main.HubClient", return_value=mock_client),
            patch("fin_assist.cli.main.render_error"),
        ):
            result = _run_main("do", "nonexistent", "do something")

        assert result == 1
        mock_client.run_agent.assert_not_called()

    def test_returns_1_on_server_startup_error(self):
        from fin_assist.cli.server import ServerStartupError

        with (
            _patch_asyncio_run(),
            patch(
                "fin_assist.cli.main.ensure_server_running",
                new_callable=AsyncMock,
                side_effect=ServerStartupError("no server"),
            ),
            patch("fin_assist.cli.main.render_error"),
        ):
            result = _run_main("do", "shell", "list files")

        assert result == 1

    def test_returns_1_on_agent_request_error(self):
        agent = _make_discovered("shell", requires_approval=False)
        mock_client = _mock_client(agents=[agent], run_error=Exception("network error"))

        with (
            _patch_asyncio_run(),
            patch(
                "fin_assist.cli.main.ensure_server_running",
                new_callable=AsyncMock,
                return_value="http://localhost:4096",
            ),
            patch("fin_assist.cli.main.HubClient", return_value=mock_client),
            patch("fin_assist.cli.main.render_error"),
        ):
            result = _run_main("do", "shell", "do something")

        assert result == 1


# ---------------------------------------------------------------------------
# `do` command — approval path
# ---------------------------------------------------------------------------


class TestDoCommandApproval:
    def test_shows_approval_widget_when_requires_approval(self):
        agent = _make_discovered("shell", requires_approval=True, supports_regenerate=True)
        mock_client = _mock_client(
            agents=[agent],
            run_result=AgentResult(success=True, output="rm -rf /tmp/x"),
        )

        from fin_assist.cli.interaction.approve import ApprovalAction

        with (
            _patch_asyncio_run(),
            patch(
                "fin_assist.cli.main.ensure_server_running",
                new_callable=AsyncMock,
                return_value="http://localhost:4096",
            ),
            patch("fin_assist.cli.main.HubClient", return_value=mock_client),
            patch(
                "fin_assist.cli.main.run_approve_widget",
                return_value=(ApprovalAction.CANCEL, None),
            ) as mock_widget,
        ):
            result = _run_main("do", "shell", "remove temp")

        mock_widget.assert_called_once()
        assert result == 0

    def test_executes_command_on_approve(self):
        agent = _make_discovered("shell", requires_approval=True)
        mock_client = _mock_client(
            agents=[agent],
            run_result=AgentResult(success=True, output="echo hi"),
        )

        from fin_assist.cli.interaction.approve import ApprovalAction

        with (
            _patch_asyncio_run(),
            patch(
                "fin_assist.cli.main.ensure_server_running",
                new_callable=AsyncMock,
                return_value="http://localhost:4096",
            ),
            patch("fin_assist.cli.main.HubClient", return_value=mock_client),
            patch(
                "fin_assist.cli.main.run_approve_widget",
                return_value=(ApprovalAction.EXECUTE, None),
            ),
            patch("fin_assist.cli.main.execute_command", return_value=0) as mock_exec,
        ):
            result = _run_main("do", "shell", "say hello")

        mock_exec.assert_called_once_with("echo hi")
        assert result == 0

    def test_reruns_with_edited_prompt_on_edit(self):
        agent = _make_discovered("shell", requires_approval=True, supports_regenerate=True)
        run_results = [
            AgentResult(success=True, output="echo first"),
            AgentResult(success=True, output="echo second"),
        ]
        mock_client = _mock_client(agents=[agent])
        mock_client.run_agent = AsyncMock(side_effect=run_results)

        from fin_assist.cli.interaction.approve import ApprovalAction

        approve_responses = [
            (ApprovalAction.EDIT, "edited prompt"),
            (ApprovalAction.EXECUTE, None),
        ]

        with (
            _patch_asyncio_run(),
            patch(
                "fin_assist.cli.main.ensure_server_running",
                new_callable=AsyncMock,
                return_value="http://localhost:4096",
            ),
            patch("fin_assist.cli.main.HubClient", return_value=mock_client),
            patch(
                "fin_assist.cli.main.run_approve_widget",
                side_effect=approve_responses,
            ),
            patch("fin_assist.cli.main.execute_command", return_value=0),
        ):
            result = _run_main("do", "shell", "original prompt")

        assert result == 0
        assert mock_client.run_agent.call_count == 2
        # Second call uses the edited prompt
        mock_client.run_agent.assert_called_with("shell", "edited prompt")

    def test_approval_widget_receives_card_meta_flags(self):
        """supports_regenerate comes from card_meta, not result.metadata."""
        agent = _make_discovered("shell", requires_approval=True, supports_regenerate=True)
        mock_client = _mock_client(
            agents=[agent],
            run_result=AgentResult(
                success=True,
                output="ls",
                metadata={"regenerate_prompt": "list files"},
            ),
        )

        from fin_assist.cli.interaction.approve import ApprovalAction

        with (
            _patch_asyncio_run(),
            patch(
                "fin_assist.cli.main.ensure_server_running",
                new_callable=AsyncMock,
                return_value="http://localhost:4096",
            ),
            patch("fin_assist.cli.main.HubClient", return_value=mock_client),
            patch(
                "fin_assist.cli.main.run_approve_widget",
                return_value=(ApprovalAction.CANCEL, None),
            ) as mock_widget,
        ):
            _run_main("do", "shell", "list files")

        _, widget_kwargs = mock_widget.call_args
        assert widget_kwargs["supports_regenerate"] is True
        assert widget_kwargs["regenerate_prompt"] == "list files"


# ---------------------------------------------------------------------------
# `talk --list` command (no server needed)
# ---------------------------------------------------------------------------


class TestTalkListCommand:
    def test_talk_list_returns_0_without_starting_server(self, tmp_path):
        mock_ensure = AsyncMock()

        with (
            _patch_asyncio_run(),
            patch("fin_assist.cli.main.SESSIONS_DIR", tmp_path),
            patch("fin_assist.cli.main.ensure_server_running", mock_ensure),
        ):
            result = _run_main("talk", "default", "--list")

        assert result == 0
        mock_ensure.assert_not_called()

    def test_talk_list_shows_sessions(self, tmp_path):
        import json

        sessions_dir = tmp_path / "default"
        sessions_dir.mkdir(parents=True)
        (sessions_dir / "swift-harbor.json").write_text(
            json.dumps({"session_id": "swift-harbor", "context_id": "ctx-abcdefgh"})
        )

        captured = []

        with (
            _patch_asyncio_run(),
            patch("fin_assist.cli.main.SESSIONS_DIR", tmp_path),
            patch("fin_assist.cli.main.console") as mock_console,
        ):
            mock_console.print.side_effect = lambda msg: captured.append(msg)
            result = _run_main("talk", "default", "--list")

        assert result == 0
        assert any("swift-harbor" in str(m) for m in captured)


# ---------------------------------------------------------------------------
# Session ID format
# ---------------------------------------------------------------------------


class TestSessionIdFormat:
    def test_saved_session_id_is_natural_language_slug(self, tmp_path):
        """Session IDs should be human-readable NL slugs, not UUID hex strings."""
        mock_client = _mock_client(agents=[_make_discovered("default")])
        mock_client.send_message = AsyncMock(
            return_value=AgentResult(success=True, output="hi", context_id="ctx-uuid-123")
        )

        saved_ids: list[str] = []

        def capture_save(agent, session_id, context_id):
            saved_ids.append(session_id)

        with (
            _patch_asyncio_run(),
            patch("fin_assist.cli.main.SESSIONS_DIR", tmp_path),
            patch(
                "fin_assist.cli.main.ensure_server_running",
                new_callable=AsyncMock,
                return_value="http://localhost:4096",
            ),
            patch("fin_assist.cli.main.HubClient", return_value=mock_client),
            patch("fin_assist.cli.main._save_session", side_effect=capture_save),
            patch(
                "fin_assist.cli.main.run_chat_loop",
                new_callable=AsyncMock,
                return_value="ctx-uuid-123",
            ),
        ):
            _run_main("talk", "default")

        assert len(saved_ids) == 1
        session_id = saved_ids[0]
        # NL slug: contains a hyphen, no raw hex UUID format
        assert "-" in session_id
        assert len(session_id) > 4  # not a truncated uuid


# ---------------------------------------------------------------------------
# `stop` command
# ---------------------------------------------------------------------------


class TestStopCommand:
    def test_stop_renders_info_and_returns_0_when_server_stopped(self):
        with (
            patch("fin_assist.cli.main.stop_server", return_value=True),
            patch("fin_assist.cli.main.render_info") as mock_info,
        ):
            result = _run_main("stop")

        assert result == 0
        mock_info.assert_called_once()

    def test_stop_renders_error_and_returns_1_when_no_server(self):
        with (
            patch("fin_assist.cli.main.stop_server", return_value=False),
            patch("fin_assist.cli.main.render_error") as mock_error,
        ):
            result = _run_main("stop")

        assert result == 1
        mock_error.assert_called_once()

    def test_stop_calls_stop_server(self):
        with (
            patch("fin_assist.cli.main.stop_server", return_value=True) as mock_stop,
            patch("fin_assist.cli.main.render_info"),
        ):
            _run_main("stop")

        mock_stop.assert_called_once()


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


class TestMainArgParsing:
    def test_no_subcommand_exits_nonzero(self):
        with pytest.raises(SystemExit) as exc_info:
            main([])
        assert exc_info.value.code != 0

    def test_unknown_subcommand_exits_nonzero(self):
        with pytest.raises(SystemExit) as exc_info:
            main(["unknown-cmd"])
        assert exc_info.value.code != 0
