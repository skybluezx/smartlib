from typing import Any
from uuid import UUID

import httpx

from .errors import SearchBackendUnavailable


class OpenSearchProjectionWriter:
    def __init__(self, base_url: str, write_alias: str, timeout_seconds: float = 5.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.write_alias = write_alias
        self.timeout_seconds = timeout_seconds
        self._client = httpx.Client(timeout=timeout_seconds)

    def deliver(self, delivery: dict[str, Any]) -> None:
        operation = delivery["operation"]
        object_id = UUID(str(delivery["object_id"]))
        if operation == "delete":
            self._delete(object_id)
            return
        if operation != "upsert" or not isinstance(delivery.get("document"), dict):
            raise ValueError("unsupported search projection delivery")
        self._upsert(object_id, delivery["document"])

    def _upsert(self, object_id: UUID, document: dict[str, Any]) -> None:
        object_version = int(document["object_version"])
        try:
            response = self._client.put(
                f"{self.base_url}/{self.write_alias}/_doc/{object_id}",
                params={
                    "version": object_version,
                    "version_type": "external_gte",
                    "refresh": "false",
                },
                json=document,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise SearchBackendUnavailable("OpenSearch projection write failed") from exc

    def _delete(self, object_id: UUID) -> None:
        try:
            response = self._client.delete(
                f"{self.base_url}/{self.write_alias}/_doc/{object_id}",
                params={"refresh": "false"},
            )
            if response.status_code != 404:
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise SearchBackendUnavailable("OpenSearch projection delete failed") from exc
