import pytest

from smartlib_platform.search.cursor import decode_offset_cursor, encode_offset_cursor
from smartlib_platform.search.errors import InvalidSearchCursor


def test_cursor_round_trip_is_backend_scoped() -> None:
    cursor = encode_offset_cursor("postgres", 20)
    assert decode_offset_cursor(cursor, "postgres") == 20
    with pytest.raises(InvalidSearchCursor):
        decode_offset_cursor(cursor, "opensearch")


@pytest.mark.parametrize("cursor", ["%%%", "e30", "eyJiYWNrZW5kIjoicG9zdGdyZXMifQ"])
def test_invalid_cursor_is_rejected(cursor: str) -> None:
    with pytest.raises(InvalidSearchCursor):
        decode_offset_cursor(cursor, "postgres")
