from fin_assist.hub.factory import create_agent_app


def test_create_agent_app_placeholder() -> None:
    assert create_agent_app(object()) is not None
