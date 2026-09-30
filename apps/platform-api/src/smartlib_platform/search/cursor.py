import base64
import json

from .errors import InvalidSearchCursor


def encode_offset_cursor(backend: str, offset: int) -> str:
    payload = json.dumps({"backend": backend, "offset": offset}, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def decode_offset_cursor(cursor: str | None, backend: str) -> int:
    if cursor is None:
        return 0
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode())
        if payload.get("backend") != backend:
            raise InvalidSearchCursor("cursor belongs to a different search backend")
        offset = payload.get("offset")
        if not isinstance(offset, int) or offset < 0:
            raise InvalidSearchCursor("cursor offset is invalid")
        return offset
    except InvalidSearchCursor:
        raise
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError, AttributeError) as exc:
        raise InvalidSearchCursor("cursor is invalid") from exc
