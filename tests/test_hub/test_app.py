from fin_assist.hub.app import create_hub_app


def test_create_hub_app() -> None:
    app = create_hub_app()

    assert app is not None
