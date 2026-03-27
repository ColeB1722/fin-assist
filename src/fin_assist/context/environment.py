from __future__ import annotations

import os
from typing import TYPE_CHECKING

from fin_assist.context.base import ContextItem, ContextProvider, ContextType

if TYPE_CHECKING:
    from fin_assist.config.schema import ContextSettings


class Environment(ContextProvider):
    def __init__(self, settings: ContextSettings | None = None) -> None:
        self._settings = settings
        self._cache: list[ContextItem] | None = None

    def _supported_types(self) -> set[ContextType]:
        types: set[ContextType] = {"env"}
        return types

    def _get_env_vars(self) -> list[str]:
        if self._settings:
            return self._settings.include_env_vars
        return ["PATH", "HOME", "USER", "PWD"]

    def search(self, query: str) -> list[ContextItem]:
        return []

    def get_item(self, id: str) -> ContextItem:
        all_items = self.get_all()
        for item in all_items:
            if item.id == id:
                return item
        return ContextItem(
            id=id,
            type="env",
            status="not_found",
            error_reason="env_var_not_found",
        )

    def get_all(self) -> list[ContextItem]:
        if self._cache is not None:
            return self._cache
        env_vars = self._get_env_vars()
        items = []
        cwd = os.getcwd()
        items.append(
            ContextItem(
                id="PWD",
                type="env",
                content=cwd,
                metadata={"name": "PWD", "source": "os.getcwd()"},
                status="available",
            )
        )
        items.append(
            ContextItem(
                id="HOME",
                type="env",
                content=os.environ.get("HOME", ""),
                metadata={"name": "HOME", "source": "environ"},
                status="available",
            )
        )
        items.append(
            ContextItem(
                id="USER",
                type="env",
                content=os.environ.get("USER", ""),
                metadata={"name": "USER", "source": "environ"},
                status="available",
            )
        )
        for var in env_vars:
            if var in ("PWD", "HOME", "USER"):
                continue
            value = os.environ.get(var, "")
            items.append(
                ContextItem(
                    id=var,
                    type="env",
                    content=value,
                    metadata={"name": var, "source": "environ"},
                    status="available",
                )
            )
        self._cache = items
        return items
