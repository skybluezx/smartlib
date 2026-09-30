from datetime import date, datetime
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Command(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    reason: str = Field(min_length=3, max_length=1000)


class SourceCommand(Command):
    code: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    name: str = Field(min_length=1, max_length=200)
    owner_department: str = Field(min_length=1, max_length=200)
    source_type: Literal["database", "api", "file", "repository", "licensed_resource", "manual"]
    endpoint: str = Field(default="", max_length=1000)

    @field_validator("endpoint")
    @classmethod
    def safe_endpoint(cls, value: str) -> str:
        if not value:
            return value
        url = urlsplit(value)
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            raise ValueError("仅登记不含账户、口令、查询参数的 HTTP(S) 地址；此操作不访问外部服务")
        return value


class AssetCommand(Command):
    code: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    name: str = Field(min_length=1, max_length=200)
    source_system_id: UUID
    governance_domain_id: UUID
    description: str = Field(default="", max_length=2000)
    asset_type: Literal[
        "database", "dataset", "api", "file", "repository", "licensed_resource", "knowledge_collection"
    ]


class DomainCommand(Command):
    code: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=2000)


class RuleCommand(Command):
    data_asset_id: UUID
    code: str = Field(pattern=r"^[a-z][a-z0-9_.-]{1,127}$")
    name: str = Field(min_length=1, max_length=200)
    field: Literal["title", "abstract", "journal_name", "publication_year", "issn", "eissn"]
    severity: Literal["low", "medium", "high", "critical"] = "medium"


class SchemaField(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    field_path: str = Field(min_length=1, max_length=200)
    data_type: Literal["string", "integer", "decimal", "boolean", "date", "datetime", "object", "array"]
    nullable: bool = True
    classification: Literal["public", "internal", "sensitive", "restricted"] = "internal"
    description: str = Field(default="", max_length=1000)


class SchemaCommand(Command):
    data_asset_id: UUID
    base_version: int = Field(ge=0)
    schema_version: str = Field(min_length=1, max_length=100)
    fields: list[SchemaField] = Field(min_length=1, max_length=200)

    @field_validator("fields")
    @classmethod
    def unique_fields(cls, fields: list[SchemaField]) -> list[SchemaField]:
        if len({field.field_path for field in fields}) != len(fields):
            raise ValueError("同一版本中字段路径不能重复")
        return fields


class LibraryCommand(Command):
    metric_code: str = Field(pattern=r"^[a-z][a-z0-9_.-]{1,63}$")
    metric_name: str = Field(min_length=1, max_length=200)
    period: date
    organization: str = Field(min_length=1, max_length=200)
    value: float = Field(ge=0, allow_inf_nan=False)
    unit: str = Field(min_length=1, max_length=50)
    source_reference: str = Field(min_length=1, max_length=1000)
    note: str = Field(default="", max_length=2000)

    @field_validator("period")
    @classmethod
    def month_start(cls, value: date) -> date:
        if value.day != 1:
            raise ValueError("馆务指标按月登记，日期请填写该月第一天")
        return value


class ApplicationCommand(Command):
    code: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    entry_path: str = Field(min_length=1, max_length=300)
    owner_department: str = Field(min_length=1, max_length=200)

    @field_validator("entry_path")
    @classmethod
    def local_path(cls, value: str) -> str:
        if (
            not value.startswith("/")
            or value.startswith("//")
            or "\\" in value
            or any(ord(c) < 32 for c in value)
        ):
            raise ValueError("应用入口必须是本站相对路径")
        return value


class SettingCommand(Command):
    code: Literal["library_name", "service_contact", "workbench_notice"]
    value: str = Field(max_length=2000)
    base_version: int = Field(ge=0)


class StateCommand(Command):
    base_updated_at: datetime
    state: str


class LicenseCommand(Command):
    data_asset_id: UUID
    license_name: str = Field(min_length=1, max_length=200)
    license_reference: str = Field(min_length=1, max_length=1000)
    allowed_content: list[str] = Field(min_length=1, max_length=50)
    allowed_purposes: list[str] = Field(min_length=1, max_length=50)
    prohibited_purposes: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("allowed_content", "allowed_purposes", "prohibited_purposes")
    @classmethod
    def nonempty_terms(cls, values: list[str]) -> list[str]:
        if any(not term.strip() or len(term) > 200 for term in values):
            raise ValueError("条款不能为空且每项不超过200字")
        return list(dict.fromkeys(term.strip() for term in values))


class HubTable(BaseModel):
    items: list[dict[str, object]]
    total: int
    page: int
    page_size: int


class LibraryRevision(LibraryCommand):
    base_version: int = Field(ge=1)
