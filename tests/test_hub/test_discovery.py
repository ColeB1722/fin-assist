from fin_assist.hub.discovery import list_agents


def test_list_agents_placeholder() -> None:
    assert list_agents() == []
