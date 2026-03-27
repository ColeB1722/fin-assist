from __future__ import annotations

from pydantic import BaseModel


class CommandResult(BaseModel):
    command: str
    warnings: list[str] = []
