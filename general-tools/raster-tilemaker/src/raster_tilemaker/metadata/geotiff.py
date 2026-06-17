from __future__ import annotations


def normalize_tag_key(key: str) -> str:
    return "".join(ch for ch in key.lower() if ch.isalnum())


def tag_value(tags: dict[str, str], key: str) -> str | None:
    target = normalize_tag_key(key)
    for tag_key, value in tags.items():
        if normalize_tag_key(tag_key) == target:
            return value.strip()
    return None
