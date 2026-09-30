from typing import Literal

from pydantic import Field

from smartlib_platform.knowledge_hub.models import Command


class WorkCommand(Command):
    category: str
    fields: dict[str, str] = Field(max_length=40)
    mode: Literal["real", "demo"]


class WorkRevision(WorkCommand):
    base_version: int = Field(ge=1)
    state: Literal["active", "withdrawn"] = "active"


class ImportCommit(Command):
    confirm: bool
