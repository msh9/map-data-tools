from __future__ import annotations

import re


def normalize_chart_name(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "", value.lower())
    if not normalized:
        raise ValueError(f"Chart name cannot be normalized: {value!r}")
    return normalized


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if not slug:
        raise ValueError(f"Chart name cannot be slugified: {value!r}")
    return slug


def parse_tac_chart_basename(stem: str) -> str:
    suffixes = (
        " TAC VFR Planning Charts",
        " TAC",
        " FLY",
        " Graphic",
        " Planning Chart",
    )
    for suffix in suffixes:
        if stem.endswith(suffix):
            base = stem[: -len(suffix)].strip()
            if base:
                return base
            break
    raise ValueError(f"Unable to parse TAC/FLY chart base name from TIFF stem: {stem!r}")
