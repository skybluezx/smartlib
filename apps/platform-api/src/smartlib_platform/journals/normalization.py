"""Unicode-safe journal title normalization."""

from __future__ import annotations

import html
import re
import unicodedata


def clean_title(value: object) -> str:
    """Return a display-safe title with decoded entities and normalized width."""
    text = html.unescape(str(value or ""))
    text = unicodedata.normalize("NFKC", text).strip()
    return re.sub(r"\s+", " ", text)


def normalized_title(value: object) -> str:
    """Return a readable, case-insensitive title while retaining every script."""

    return clean_title(value).casefold()


def journal_key(value: object) -> str:
    """Return a comparison key that keeps Unicode letters and numbers."""

    title = normalized_title(value).replace("&", " and ")
    title = re.sub(r"^the\s+", "", title)
    return "".join(character for character in title if character.isalnum())
