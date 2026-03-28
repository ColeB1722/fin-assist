from fin_assist.agents.shell import ShellAgent


def test_shell_agent_metadata() -> None:
    agent = ShellAgent(config=None, credentials=None)  # type: ignore[arg-type]

    assert agent.name == "shell"
    assert agent.agent_card_metadata.multi_turn is False
    assert agent.agent_card_metadata.supports_thinking is False


def test_shell_agent_run_returns_insert_command_metadata() -> None:
    agent = ShellAgent(config=None, credentials=None)  # type: ignore[arg-type]

    result = __import__("asyncio").run(agent.run("echo hi", []))

    assert result.success is True
    assert result.metadata["accept_action"] == "insert_command"
