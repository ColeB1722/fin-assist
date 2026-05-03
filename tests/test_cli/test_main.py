"""Tests for cli/main.py — CLI command dispatch.

Strategy: `main()` calls `asyncio.run()` for async commands. In tests we patch
`asyncio.run` to execute the coroutine synchronously via
`asyncio.get_event_loop().run_until_complete()`, avoiding the "cannot be called
from a running event loop" error that occurs in pytest-asyncio contexts.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fin_assist.agents.metadata import AgentCardMeta, AgentResult
from fin_assist.cli.client import DiscoveredAgent, StreamEvent
from fin_assist.cli.interaction.response import PostResponseAction, PostResponseResult
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
) -> DiscoveredAgent:
    return DiscoveredAgent(
        name=name,
        description="test agent",
        url=f"http://localhost/agents/{name}/",
        card_meta=AgentCardMeta(),
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

        async def _failing_stream(*args, **kwargs):
            raise run_error
            yield

        client.stream_agent = MagicMock(side_effect=_failing_stream)
    else:
        result = run_result or AgentResult(success=True, output="")

        async def _streaming_result(*args, **kwargs) -> AsyncIterator[StreamEvent]:
            yield StreamEvent(kind="text_delta", text=result.output)
            yield StreamEvent(kind="completed", result=result)

        client.stream_agent = MagicMock(side_effect=_streaming_result)

    return client


# ---------------------------------------------------------------------------
# `serve` command
# ---------------------------------------------------------------------------


class TestServeCommand:
    def test_serve_starts_uvicorn(self):
        mock_server = MagicMock()
        with (
            patch("fin_assist.hub.app.create_hub_app", return_value=MagicMock()),
            patch("fin_assist.hub.logging.configure_logging"),
            patch("fin_assist.hub.pidfile.acquire"),
            patch("uvicorn.Config"),
            patch("uvicorn.Server", return_value=mock_server),
            patch("socket.socket", return_value=MagicMock()),
            patch("fin_assist.cli.main.asyncio.run"),
        ):
            result = _run_main("serve")

        mock_server.serve.assert_called_once()
        assert result == 0

    def test_serve_allows_host_override(self):
        mock_server = MagicMock()
        with (
            patch("fin_assist.hub.app.create_hub_app", return_value=MagicMock()),
            patch("fin_assist.hub.logging.configure_logging"),
            patch("fin_assist.hub.pidfile.acquire"),
            patch("uvicorn.Config") as mock_config_cls,
            patch("uvicorn.Server", return_value=mock_server),
            patch("socket.socket", return_value=MagicMock()),
            patch("fin_assist.cli.main.asyncio.run"),
        ):
            _run_main("serve", "--host", "0.0.0.0")

        call_kwargs = mock_config_cls.call_args
        assert call_kwargs.kwargs.get("host") == "0.0.0.0"

    def test_serve_allows_port_override(self):
        mock_server = MagicMock()
        with (
            patch("fin_assist.hub.app.create_hub_app", return_value=MagicMock()),
            patch("fin_assist.hub.logging.configure_logging"),
            patch("fin_assist.hub.pidfile.acquire"),
            patch("uvicorn.Config") as mock_config_cls,
            patch("uvicorn.Server", return_value=mock_server),
            patch("socket.socket", return_value=MagicMock()),
            patch("fin_assist.cli.main.asyncio.run"),
        ):
            _run_main("serve", "--port", "8080")

        call_kwargs = mock_config_cls.call_args
        assert call_kwargs.kwargs.get("port") == 8080

    def test_serve_returns_1_on_port_in_use(self):
        import errno

        with (
            patch("socket.socket") as mock_sock_cls,
            patch("fin_assist.cli.main.render_error") as mock_error,
        ):
            mock_sock = MagicMock()
            mock_sock.bind.side_effect = OSError(errno.EADDRINUSE, "Address already in use")
            mock_sock_cls.return_value = mock_sock
            result = _run_main("serve")

        assert result == 1
        assert "already in use" in mock_error.call_args[0][0]

    def test_serve_returns_1_on_permission_denied(self):
        import errno

        with (
            patch("socket.socket") as mock_sock_cls,
            patch("fin_assist.cli.main.render_error") as mock_error,
        ):
            mock_sock = MagicMock()
            mock_sock.bind.side_effect = OSError(errno.EACCES, "Permission denied")
            mock_sock_cls.return_value = mock_sock
            result = _run_main("serve")

        assert result == 1
        assert "Permission denied" in mock_error.call_args[0][0]

    def test_serve_passes_prebound_socket_to_server(self):
        mock_server = MagicMock()
        mock_sock = MagicMock()
        with (
            patch("fin_assist.hub.app.create_hub_app", return_value=MagicMock()),
            patch("fin_assist.hub.logging.configure_logging"),
            patch("fin_assist.hub.pidfile.acquire"),
            patch("uvicorn.Config"),
            patch("uvicorn.Server", return_value=mock_server),
            patch("socket.socket", return_value=mock_sock),
            patch("fin_assist.cli.main.asyncio.run"),
        ):
            result = _run_main("serve")

        serve_call_kwargs = mock_server.serve.call_args
        assert serve_call_kwargs.kwargs.get("sockets") == [mock_sock]
        assert result == 0


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
            patch("fin_assist.cli.client.HubClient") as mock_cls,
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
            patch("fin_assist.cli.client.HubClient") as mock_cls,
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
            patch("fin_assist.cli.client.HubClient") as mock_cls,
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
            patch("fin_assist.cli.client.HubClient") as mock_cls,
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
            patch("fin_assist.cli.client.HubClient", return_value=mock_client),
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
        agent = _make_discovered("shell")
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
            patch("fin_assist.cli.client.HubClient", return_value=mock_client),
            patch(
                "fin_assist.cli.interaction.streaming.render_stream",
                new_callable=AsyncMock,
                return_value=(AgentResult(success=True, output="ls -la"), []),
            ),
            patch(
                "fin_assist.cli.interaction.response.handle_post_response",
                new_callable=AsyncMock,
                return_value=PostResponseResult(action=PostResponseAction.CONTINUE),
            ),
        ):
            result = _run_main("do", "--agent", "shell", "list files")

        assert result == 0
        assert mock_client.discover_agents.call_count >= 1
        mock_client.stream_agent.assert_called_once()

    def test_returns_1_for_unknown_agent(self):
        mock_client = _mock_client(agents=[_make_discovered("default")])

        with (
            _patch_asyncio_run(),
            patch(
                "fin_assist.cli.main.ensure_server_running",
                new_callable=AsyncMock,
                return_value="http://localhost:4096",
            ),
            patch("fin_assist.cli.client.HubClient", return_value=mock_client),
            patch("fin_assist.cli.main.render_error"),
        ):
            result = _run_main("do", "--agent", "nonexistent", "do something")

        assert result == 1
        mock_client.stream_agent.assert_not_called()

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
            result = _run_main("do", "--agent", "shell", "list files")

        assert result == 1

    def test_returns_1_on_agent_request_error(self):
        agent = _make_discovered("shell")
        mock_client = _mock_client(agents=[agent], run_error=Exception("network error"))

        with (
            _patch_asyncio_run(),
            patch(
                "fin_assist.cli.main.ensure_server_running",
                new_callable=AsyncMock,
                return_value="http://localhost:4096",
            ),
            patch("fin_assist.cli.client.HubClient", return_value=mock_client),
            patch("fin_assist.cli.main.render_error"),
        ):
            result = _run_main("do", "--agent", "shell", "do something")

        assert result == 1


# ---------------------------------------------------------------------------
# `talk --list` command (no server needed)
# ---------------------------------------------------------------------------


class TestTalkListCommand:
    def test_talk_list_returns_0_without_starting_server(self, tmp_path):
        mock_ensure = AsyncMock()

        with (
            _patch_asyncio_run(),
            patch("fin_assist.cli.display.SESSIONS_DIR", tmp_path),
            patch("fin_assist.cli.main.ensure_server_running", mock_ensure),
        ):
            result = _run_main("talk", "--agent", "default", "--list")

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
            patch("fin_assist.cli.display.SESSIONS_DIR", tmp_path),
            patch("fin_assist.cli.display.console") as mock_console,
        ):
            mock_console.print.side_effect = lambda msg: captured.append(msg)
            result = _run_main("talk", "--agent", "default", "--list")

        assert result == 0
        assert any("swift-harbor" in str(m) for m in captured)

    def test_talk_list_sorts_most_recent_first(self, tmp_path):
        import json
        import os

        sessions_dir = tmp_path / "default"
        sessions_dir.mkdir(parents=True)

        older_file = sessions_dir / "older.json"
        older_file.write_text(json.dumps({"session_id": "older", "context_id": "ctx-aaaaaaaa"}))
        newer_file = sessions_dir / "newer.json"
        newer_file.write_text(json.dumps({"session_id": "newer", "context_id": "ctx-bbbbbbbb"}))
        os.utime(older_file, (1000, 1000))
        os.utime(newer_file, (2000, 2000))

        captured = []

        with (
            _patch_asyncio_run(),
            patch("fin_assist.cli.display.SESSIONS_DIR", tmp_path),
            patch("fin_assist.cli.display.console") as mock_console,
        ):
            mock_console.print.side_effect = lambda msg: captured.append(msg)
            result = _run_main("talk", "--agent", "default", "--list")

        assert result == 0
        slugs = [m for m in captured if "context:" in str(m)]
        assert "newer" in str(slugs[0])
        assert "older" in str(slugs[1])


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
            patch("fin_assist.cli.client.HubClient", return_value=mock_client),
            patch("fin_assist.cli.main._save_session", side_effect=capture_save),
            patch(
                "fin_assist.cli.interaction.chat.run_chat_loop",
                new_callable=AsyncMock,
                return_value="ctx-uuid-123",
            ),
        ):
            _run_main("talk", "--agent", "default")

        assert len(saved_ids) == 1
        session_id = saved_ids[0]
        # NL slug: contains a hyphen, no raw hex UUID format
        assert "-" in session_id
        assert len(session_id) > 4  # not a truncated uuid


# ---------------------------------------------------------------------------
# `stop` command
# ---------------------------------------------------------------------------


class TestStartCommand:
    def test_start_calls_ensure_server_running(self):
        with (
            _patch_asyncio_run(),
            patch(
                "fin_assist.cli.main.ensure_server_running",
                new_callable=AsyncMock,
                return_value="http://127.0.0.1:4096",
            ) as mock_ensure,
            patch("fin_assist.cli.main.render_info"),
        ):
            result = _run_main("start")

        mock_ensure.assert_called_once()
        assert result == 0

    def test_start_renders_info_with_url(self):
        with (
            _patch_asyncio_run(),
            patch(
                "fin_assist.cli.main.ensure_server_running",
                new_callable=AsyncMock,
                return_value="http://127.0.0.1:4096",
            ),
            patch("fin_assist.cli.main.render_info") as mock_info,
        ):
            _run_main("start")

        mock_info.assert_called_once_with("Hub running at http://127.0.0.1:4096")

    def test_start_returns_1_on_startup_error(self):
        from fin_assist.cli.server import ServerStartupError

        with (
            _patch_asyncio_run(),
            patch(
                "fin_assist.cli.main.ensure_server_running",
                new_callable=AsyncMock,
                side_effect=ServerStartupError("failed"),
            ),
            patch("fin_assist.cli.main.render_error") as mock_error,
        ):
            result = _run_main("start")

        assert result == 1
        mock_error.assert_called_once()


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

    def test_stop_passes_port_to_stop_server(self):
        with (
            patch("fin_assist.cli.main.stop_server", return_value=True) as mock_stop,
            patch("fin_assist.cli.main.render_info"),
        ):
            _run_main("stop")

        _, kwargs = mock_stop.call_args
        assert "port" in kwargs


# ---------------------------------------------------------------------------
# status command
# ---------------------------------------------------------------------------


class TestStatusCommand:
    def test_status_returns_0_when_healthy(self):
        from fin_assist.cli.server import HubStatus

        mock_status = HubStatus(
            healthy=True, base_url="http://127.0.0.1:4096", pid=12345, pid_file_exists=True
        )
        with (
            patch("fin_assist.cli.main.check_status", return_value=mock_status),
            patch("fin_assist.cli.main.render_info") as mock_info,
        ):
            result = _run_main("status")

        assert result == 0
        info_text = mock_info.call_args[0][0]
        assert "running" in info_text.lower() or "12345" in info_text

    def test_status_returns_0_when_not_running(self):
        from fin_assist.cli.server import HubStatus

        mock_status = HubStatus(
            healthy=False, base_url="http://127.0.0.1:4096", pid=None, pid_file_exists=False
        )
        with (
            patch("fin_assist.cli.main.check_status", return_value=mock_status),
            patch("fin_assist.cli.main.render_info") as mock_info,
        ):
            result = _run_main("status")

        assert result == 0
        info_text = mock_info.call_args[0][0]
        assert "not running" in info_text.lower()

    def test_status_warns_about_orphaned_server(self):
        from fin_assist.cli.server import HubStatus

        mock_status = HubStatus(
            healthy=True, base_url="http://127.0.0.1:4096", pid=12345, pid_file_exists=False
        )
        with (
            patch("fin_assist.cli.main.check_status", return_value=mock_status),
            patch("fin_assist.cli.main.render_info") as mock_info,
        ):
            result = _run_main("status")

        assert result == 0
        info_text = mock_info.call_args[0][0]
        assert "orphan" in info_text.lower() or "PID file missing" in info_text


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


class TestDefaultAgentResolution:
    def test_do_without_agent_and_no_default_returns_1(self):
        from fin_assist.config.schema import Config

        with (
            patch("fin_assist.cli.main.load_config", return_value=(Config(), None)),
            patch("fin_assist.cli.main.render_error") as mock_error,
        ):
            result = _run_main("do")
        assert result == 1
        msg = mock_error.call_args[0][0]
        assert "No agents" in msg or "No default" in msg

    def test_talk_without_agent_and_no_default_returns_1(self):
        from fin_assist.config.schema import Config

        with (
            patch("fin_assist.cli.main.load_config", return_value=(Config(), None)),
            patch("fin_assist.cli.main.render_error") as mock_error,
        ):
            result = _run_main("talk")
        assert result == 1
        msg = mock_error.call_args[0][0]
        assert "No agents" in msg or "No default" in msg

    def test_do_uses_default_agent_from_config(self):
        agent = _make_discovered("my-agent")
        mock_client = _mock_client(
            agents=[agent],
            run_result=AgentResult(success=True, output="ok"),
        )

        mock_fp = MagicMock()
        mock_fp.ask = AsyncMock(return_value="hello")

        with (
            _patch_asyncio_run(),
            patch(
                "fin_assist.cli.main.ensure_server_running",
                new_callable=AsyncMock,
                return_value="http://localhost:4096",
            ),
            patch("fin_assist.cli.client.HubClient", return_value=mock_client),
            patch(
                "fin_assist.cli.interaction.streaming.render_stream",
                new_callable=AsyncMock,
                return_value=(AgentResult(success=True, output="ok"), []),
            ),
            patch(
                "fin_assist.cli.interaction.response.handle_post_response",
                new_callable=AsyncMock,
                return_value=PostResponseResult(action=PostResponseAction.CONTINUE),
            ),
            patch("fin_assist.cli.main.load_config") as mock_load,
            patch("fin_assist.cli.interaction.prompt.FinPrompt", return_value=mock_fp),
        ):
            from fin_assist.config.schema import Config, GeneralSettings

            config = Config(general=GeneralSettings(default_agent="my-agent"))
            mock_load.return_value = (config, None)
            result = _run_main("do")

        assert result == 0
        mock_client.stream_agent.assert_called_once()
        assert mock_client.stream_agent.call_args[0][0] == "my-agent"


class TestDoInputPanel:
    def test_no_prompt_opens_input_panel(self):
        agent = _make_discovered("shell")
        mock_client = _mock_client(
            agents=[agent],
            run_result=AgentResult(success=True, output="response"),
        )

        mock_fp = MagicMock()
        mock_fp.ask = AsyncMock(return_value="list files")

        with (
            _patch_asyncio_run(),
            patch(
                "fin_assist.cli.main.ensure_server_running",
                new_callable=AsyncMock,
                return_value="http://localhost:4096",
            ),
            patch("fin_assist.cli.client.HubClient", return_value=mock_client),
            patch(
                "fin_assist.cli.interaction.streaming.render_stream",
                new_callable=AsyncMock,
                return_value=(AgentResult(success=True, output="response"), []),
            ),
            patch(
                "fin_assist.cli.interaction.response.handle_post_response",
                new_callable=AsyncMock,
                return_value=PostResponseResult(action=PostResponseAction.CONTINUE),
            ),
            patch("fin_assist.cli.interaction.prompt.FinPrompt", return_value=mock_fp),
        ):
            result = _run_main("do", "--agent", "shell")

        assert result == 0
        mock_fp.ask.assert_called_once_with("> ")

    def test_no_prompt_cancelled_returns_0(self):
        agent = _make_discovered("shell")
        mock_client = _mock_client(agents=[agent])

        mock_fp = MagicMock()
        mock_fp.ask = AsyncMock(side_effect=KeyboardInterrupt)

        with (
            _patch_asyncio_run(),
            patch(
                "fin_assist.cli.main.ensure_server_running",
                new_callable=AsyncMock,
                return_value="http://localhost:4096",
            ),
            patch("fin_assist.cli.client.HubClient", return_value=mock_client),
            patch("fin_assist.cli.main.render_info"),
            patch("fin_assist.cli.interaction.prompt.FinPrompt", return_value=mock_fp),
        ):
            result = _run_main("do", "--agent", "shell")

        assert result == 0
        mock_client.stream_agent.assert_not_called()

    def test_no_prompt_empty_input_returns_0(self):
        agent = _make_discovered("shell")
        mock_client = _mock_client(agents=[agent])

        mock_fp = MagicMock()
        mock_fp.ask = AsyncMock(return_value="   ")

        with (
            _patch_asyncio_run(),
            patch(
                "fin_assist.cli.main.ensure_server_running",
                new_callable=AsyncMock,
                return_value="http://localhost:4096",
            ),
            patch("fin_assist.cli.client.HubClient", return_value=mock_client),
            patch("fin_assist.cli.interaction.prompt.FinPrompt", return_value=mock_fp),
        ):
            result = _run_main("do", "--agent", "shell")

        assert result == 0
        mock_client.stream_agent.assert_not_called()

    def test_edit_flag_opens_prefilled_input(self):
        agent = _make_discovered("shell")
        mock_client = _mock_client(
            agents=[agent],
            run_result=AgentResult(success=True, output="response"),
        )

        mock_fp = MagicMock()
        mock_fp.ask = AsyncMock(return_value="edited prompt")

        with (
            _patch_asyncio_run(),
            patch(
                "fin_assist.cli.main.ensure_server_running",
                new_callable=AsyncMock,
                return_value="http://localhost:4096",
            ),
            patch("fin_assist.cli.client.HubClient", return_value=mock_client),
            patch(
                "fin_assist.cli.interaction.streaming.render_stream",
                new_callable=AsyncMock,
                return_value=(AgentResult(success=True, output="response"), []),
            ),
            patch(
                "fin_assist.cli.interaction.response.handle_post_response",
                new_callable=AsyncMock,
                return_value=PostResponseResult(action=PostResponseAction.CONTINUE),
            ),
            patch("fin_assist.cli.interaction.prompt.FinPrompt", return_value=mock_fp),
        ):
            result = _run_main("do", "--agent", "shell", "--edit", "original prompt")

        assert result == 0
        mock_fp.ask.assert_called_once_with("> ", default="original prompt")

    def test_edit_cancelled_returns_0(self):
        agent = _make_discovered("shell")
        mock_client = _mock_client(agents=[agent])

        mock_fp = MagicMock()
        mock_fp.ask = AsyncMock(side_effect=KeyboardInterrupt)

        with (
            _patch_asyncio_run(),
            patch(
                "fin_assist.cli.main.ensure_server_running",
                new_callable=AsyncMock,
                return_value="http://localhost:4096",
            ),
            patch("fin_assist.cli.client.HubClient", return_value=mock_client),
            patch("fin_assist.cli.main.render_info"),
            patch("fin_assist.cli.interaction.prompt.FinPrompt", return_value=mock_fp),
        ):
            result = _run_main("do", "--agent", "shell", "--edit", "prompt")

        assert result == 0
        mock_client.stream_agent.assert_not_called()

    def test_prompt_without_edit_sends_immediately(self):
        agent = _make_discovered("shell")
        mock_client = _mock_client(
            agents=[agent],
            run_result=AgentResult(success=True, output="response"),
        )

        with (
            _patch_asyncio_run(),
            patch(
                "fin_assist.cli.main.ensure_server_running",
                new_callable=AsyncMock,
                return_value="http://localhost:4096",
            ),
            patch("fin_assist.cli.client.HubClient", return_value=mock_client),
            patch(
                "fin_assist.cli.interaction.streaming.render_stream",
                new_callable=AsyncMock,
                return_value=(AgentResult(success=True, output="response"), []),
            ),
            patch(
                "fin_assist.cli.interaction.response.handle_post_response",
                new_callable=AsyncMock,
                return_value=PostResponseResult(action=PostResponseAction.CONTINUE),
            ),
        ):
            result = _run_main("do", "--agent", "shell", "list files")

        assert result == 0
        mock_client.stream_agent.assert_called_once()

    def test_prompt_with_default_agent_sends_immediately(self):
        agent = _make_discovered("my-agent")
        mock_client = _mock_client(
            agents=[agent],
            run_result=AgentResult(success=True, output="response"),
        )

        with (
            _patch_asyncio_run(),
            patch(
                "fin_assist.cli.main.ensure_server_running",
                new_callable=AsyncMock,
                return_value="http://localhost:4096",
            ),
            patch("fin_assist.cli.client.HubClient", return_value=mock_client),
            patch(
                "fin_assist.cli.interaction.streaming.render_stream",
                new_callable=AsyncMock,
                return_value=(AgentResult(success=True, output="response"), []),
            ),
            patch(
                "fin_assist.cli.interaction.response.handle_post_response",
                new_callable=AsyncMock,
                return_value=PostResponseResult(action=PostResponseAction.CONTINUE),
            ),
            patch("fin_assist.cli.main.load_config") as mock_load,
        ):
            from fin_assist.config.schema import Config, GeneralSettings

            config = Config(general=GeneralSettings(default_agent="my-agent"))
            mock_load.return_value = (config, None)
            result = _run_main("do", "list files")

        assert result == 0
        mock_client.stream_agent.assert_called_once()


# ---------------------------------------------------------------------------
# `list` command
# ---------------------------------------------------------------------------


class TestListCommand:
    def test_list_tools_prints_all_tools(self):
        captured: list[str] = []
        with patch("fin_assist.cli.main.console") as mock_console:
            mock_console.print.side_effect = lambda msg="": captured.append(str(msg))
            result = _run_main("list", "tools")
        assert result == 0
        # At least one known built-in tool should be rendered.
        assert any("read_file" in line for line in captured)

    def test_list_prompts_prints_all_prompts(self):
        captured: list[str] = []
        with patch("fin_assist.cli.main.console") as mock_console:
            mock_console.print.side_effect = lambda msg="": captured.append(str(msg))
            result = _run_main("list", "prompts")
        assert result == 0
        # Registered prompts include at least "shell" (see agents/registry.py).
        assert any("shell" in line for line in captured)

    def test_list_output_types_prints_all_types(self):
        captured: list[str] = []
        with patch("fin_assist.cli.main.console") as mock_console:
            mock_console.print.side_effect = lambda msg="": captured.append(str(msg))
            result = _run_main("list", "output-types")
        assert result == 0
        # Registered output types include "text" and "command".
        assert any("text" in line for line in captured)
        assert any("command" in line for line in captured)

    def test_list_invalid_resource_returns_nonzero(self):
        with pytest.raises(SystemExit):
            _run_main("list", "bogus")

    def test_list_tools_no_hub_connection_needed(self):
        with patch("fin_assist.cli.main.ensure_server_running") as mock_ensure:
            result = _run_main("list", "tools")
        mock_ensure.assert_not_called()
        assert result == 0


class TestResolveSkill:
    def test_no_skills_returns_prompt_unchanged(self):
        from fin_assist.cli.main import _resolve_skill
        from fin_assist.config.schema import Config

        config = Config()
        prompt, override = _resolve_skill("test", None, "hello", config)
        assert prompt == "hello"
        assert override is None

    def test_explicit_skill_name_resolves(self):
        from fin_assist.cli.main import _resolve_skill
        from fin_assist.config.schema import AgentConfig, Config, SkillConfig

        config = Config(
            agents={
                "git": AgentConfig(
                    system_prompt="git",
                    skills={
                        "commit": SkillConfig(
                            description="Commit skill",
                            prompt_template="git-commit",
                            entry_prompt="Analyze current changes and commit.",
                        ),
                    },
                ),
            }
        )
        prompt, override = _resolve_skill("git", "commit", "commit", config)
        assert prompt == "Analyze current changes and commit."
        assert override == "git-commit"

    def test_prompt_matches_skill_name(self):
        from fin_assist.cli.main import _resolve_skill
        from fin_assist.config.schema import AgentConfig, Config, SkillConfig

        config = Config(
            agents={
                "git": AgentConfig(
                    system_prompt="git",
                    skills={
                        "commit": SkillConfig(
                            entry_prompt="Analyze current changes and commit.",
                        ),
                    },
                ),
            }
        )
        prompt, override = _resolve_skill("git", None, "commit", config)
        assert prompt == "Analyze current changes and commit."

    def test_prompt_does_not_match_skill(self):
        from fin_assist.cli.main import _resolve_skill
        from fin_assist.config.schema import AgentConfig, Config, SkillConfig

        config = Config(
            agents={
                "git": AgentConfig(
                    system_prompt="git",
                    skills={
                        "commit": SkillConfig(
                            entry_prompt="Analyze current changes.",
                        ),
                    },
                ),
            }
        )
        prompt, override = _resolve_skill("git", None, "status check", config)
        assert prompt == "status check"
        assert override is None

    def test_skill_without_entry_prompt_uses_original(self):
        from fin_assist.cli.main import _resolve_skill
        from fin_assist.config.schema import AgentConfig, Config, SkillConfig

        config = Config(
            agents={
                "git": AgentConfig(
                    system_prompt="git",
                    skills={
                        "commit": SkillConfig(
                            prompt_template="git-commit",
                        ),
                    },
                ),
            }
        )
        prompt, override = _resolve_skill("git", "commit", "commit", config)
        assert prompt == "commit"
        assert override == "git-commit"

    def test_unknown_agent_returns_prompt_unchanged(self):
        from fin_assist.cli.main import _resolve_skill
        from fin_assist.config.schema import Config

        config = Config()
        prompt, override = _resolve_skill("nonexistent", None, "hello", config)
        assert prompt == "hello"
        assert override is None
