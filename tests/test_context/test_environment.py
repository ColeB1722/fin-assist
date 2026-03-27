from __future__ import annotations

from unittest.mock import MagicMock, patch

from fin_assist.context.environment import Environment


class TestEnvironment:
    def test_supported_types(self) -> None:
        env = Environment()
        assert env._supported_types() == {"env"}

    def test_supports_env_context(self) -> None:
        env = Environment()
        assert env.supports_context("env") is True
        assert env.supports_context("file") is False

    def test_search_returns_empty(self) -> None:
        env = Environment()
        result = env.search("test")
        assert result == []

    def test_get_item_pwd(self) -> None:
        env = Environment()
        with patch("os.getcwd", return_value="/home/user/project"):
            result = env.get_item("PWD")
            assert result is not None
            assert result.id == "PWD"
            assert result.content == "/home/user/project"

    def test_get_item_home(self) -> None:
        env = Environment()
        with patch.dict("os.environ", {"HOME": "/home/user"}):
            result = env.get_item("HOME")
            assert result is not None
            assert result.id == "HOME"
            assert result.content == "/home/user"

    def test_get_item_user(self) -> None:
        env = Environment()
        with patch.dict("os.environ", {"USER": "testuser"}):
            result = env.get_item("USER")
            assert result is not None
            assert result.id == "USER"
            assert result.content == "testuser"

    def test_get_item_unknown(self) -> None:
        env = Environment()
        with patch.dict("os.environ", {}, clear=True):
            with patch("os.getcwd", return_value="/test"):
                env._cache = None
                result = env.get_item("UNKNOWN_VAR")
                assert result is not None
                assert result.status == "not_found"
                assert result.error_reason == "env_var_not_found"

    def test_get_all_returns_all_env_items(self) -> None:
        env = Environment()
        with patch("os.getcwd", return_value="/test"):
            with patch.dict("os.environ", {"HOME": "/home", "USER": "me"}):
                env._cache = None
                result = env.get_all()
                assert len(result) >= 3
                ids = {item.id for item in result}
                assert "PWD" in ids
                assert "HOME" in ids
                assert "USER" in ids

    def test_get_all_is_cached(self) -> None:
        env = Environment()
        with patch("os.getcwd", return_value="/test"):
            with patch.dict("os.environ", {"HOME": "/home", "USER": "me"}):
                result1 = env.get_all()
                result2 = env.get_all()
                assert result1 is result2

    def test_cache_is_invalidated_on_new_instance(self) -> None:
        from fin_assist.config.schema import ContextSettings

        settings = ContextSettings(include_env_vars=["PATH", "SHELL"])
        env = Environment(settings=settings)

        with patch("os.getcwd", return_value="/test"):
            with patch.dict(
                "os.environ",
                {"HOME": "/home", "USER": "me", "PATH": "/usr/bin", "SHELL": "/bin/bash"},
                clear=False,
            ):
                result1 = env.get_all()
                env2 = Environment(settings=settings)
                result2 = env2.get_all()
                assert result1 is not result2

    def test_get_env_vars_defaults(self) -> None:
        env = Environment()
        result = env._get_env_vars()
        assert "PATH" in result
        assert "HOME" in result
        assert "USER" in result
        assert "PWD" in result

    def test_get_env_vars_from_settings(self) -> None:
        from fin_assist.config.schema import ContextSettings

        settings = ContextSettings(include_env_vars=["CUSTOM_VAR"])
        env = Environment(settings=settings)
        result = env._get_env_vars()
        assert result == ["CUSTOM_VAR"]
