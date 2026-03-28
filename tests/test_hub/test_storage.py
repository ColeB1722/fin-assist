from fin_assist.hub.storage import SQLiteStorage


def test_storage_placeholder() -> None:
    assert SQLiteStorage() is not None
