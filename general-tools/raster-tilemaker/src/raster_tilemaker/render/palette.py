from __future__ import annotations

from collections.abc import Mapping, Sequence


def _validate_palette_colormap(colormap) -> None:
    if not isinstance(colormap, Mapping) or not colormap:
        raise ValueError("colormap is missing or empty")
    for key, value in colormap.items():
        if not isinstance(key, int) or not (0 <= key <= 255):
            raise ValueError("colormap has invalid index; expected integer 0-255")
        if (
            not isinstance(value, Sequence)
            or isinstance(value, (str, bytes))
            or len(value) not in (3, 4)
        ):
            raise ValueError("colormap has invalid color tuple; expected 3 or 4 channels")
        for channel in value:
            if not isinstance(channel, int) or not (0 <= channel <= 255):
                raise ValueError("colormap has invalid channel value; expected integer 0-255")


def _build_palette_lut(colormap, *, with_alpha: bool):
    import numpy as np

    _validate_palette_colormap(colormap)
    channels = 4 if with_alpha else 3
    lut = np.zeros((256, channels), dtype=np.uint8)
    if with_alpha:
        lut[:, 3] = 255
    for key, value in colormap.items():
        if 0 <= key < 256:
            lut[key, :3] = value[:3]
            if with_alpha and len(value) >= 4:
                lut[key, 3] = value[3]
    return lut


def apply_palette(data, colormap):
    lut = _build_palette_lut(colormap, with_alpha=False)
    return lut[data]


def apply_palette_rgba(data, colormap):
    lut = _build_palette_lut(colormap, with_alpha=True)
    return lut[data]
