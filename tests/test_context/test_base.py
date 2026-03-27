from __future__ import annotations

from fin_assist.context.base import ContextItem, ContextProvider, ContextType


class TestContextItem:
    def test_context_item_creation(self) -> None:
        item = ContextItem(
            id="test-1",
            type="file",
            content="file content",
            metadata={"path": "/test/file.py"},
        )
        assert item.id == "test-1"
        assert item.type == "file"
        assert item.content == "file content"
        assert item.metadata == {"path": "/test/file.py"}

    def test_context_item_default_metadata(self) -> None:
        item = ContextItem(id="test-1", type="env", content="value")
        assert item.metadata == {}

    def test_context_item_with_git_diff_type(self) -> None:
        item = ContextItem(id="git_diff", type="git_diff", content="+new line")
        assert item.type == "git_diff"

    def test_context_item_with_history_type(self) -> None:
        item = ContextItem(id="0", type="history", content="ls -la")
        assert item.type == "history"


class TestContextProvider:
    def test_context_item_type_literal_values(self) -> None:
        valid_types: set[ContextType] = {
            "file",
            "git_diff",
            "git_log",
            "git_status",
            "history",
            "env",
        }
        assert "file" in valid_types
        assert "git_diff" in valid_types
        assert "git_log" in valid_types
        assert "git_status" in valid_types
        assert "history" in valid_types
        assert "env" in valid_types


class TestContextProviderABC:
    def test_search_method_exists(self) -> None:
        assert hasattr(ContextProvider, "search")

    def test_get_item_method_exists(self) -> None:
        assert hasattr(ContextProvider, "get_item")

    def test_get_all_method_exists(self) -> None:
        assert hasattr(ContextProvider, "get_all")

    def test_supports_context_delegates_to_supported_types(self) -> None:
        class FakeProvider(ContextProvider):
            def _supported_types(self) -> set[ContextType]:
                return {"file"}

            def search(self, query: str) -> list[ContextItem]:
                return []

            def get_item(self, id: str) -> ContextItem | None:
                return None

            def get_all(self) -> list[ContextItem]:
                return []

        provider = FakeProvider()
        assert provider.supports_context("file") is True
        assert provider.supports_context("history") is False
