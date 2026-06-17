"""Per-tile band processing: read R/G/B from CDSE, stretch to uint8 RGB GeoTIFF.

The tone-mapping pipeline reproduces the Sentinel Hub reference script:
  https://custom-scripts.sentinel-hub.com/sentinel2-quarterly-cloudless-mosaic/true-color/

It applies in order: DN→reflectance scaling, sigmoidal contrast stretch,
gamma, saturation boost, sRGB OETF, uint8 quantization. Note that the sRGB
OETF is applied on a signal that has already been gamma-adjusted — this is
not a principled color pipeline but matches the reference script exactly.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
from osgeo import gdal

from sentinel_mosaic.search import MosaicTile

logger = logging.getLogger(__name__)

SENTINEL_L3_MOSAIC_SCALE = 10000
_WINDOW_PIXELS = 2048


@dataclass(frozen=True)
class ToneMapParams:
    """Parameters for the Sentinel Hub true-color tone-mapping pipeline."""

    gamma: float = 1.8
    gamma_offset: float = 0.01
    saturation: float = 1.15
    middle_reflectance: float = 0.13
    maximum_reflectance: float = 3.0


DEFAULT_TONE_MAP = ToneMapParams()


def _resolve_gdal_path(href: str) -> str:
    """Map HTTPS / S3 hrefs to GDAL virtual filesystem paths."""
    if href.startswith("s3://"):
        return f"/vsis3/{href[5:]}"
    if href.startswith("http://") or href.startswith("https://"):
        return f"/vsicurl/{href}"
    return href


def _contrast_stretch_and_clip(band: np.ndarray, tx: float, ty: float, max_c: float) -> np.ndarray:
    """Sigmoidal contrast stretch: reflectance → [0,1] with midpoint ``tx``."""
    clipped = np.clip(band / max_c, 0, 1.0)
    return (
        clipped
        * (clipped * (tx / max_c + ty - 1) - ty)
        / (clipped * (2 * tx / max_c - 1) - tx / max_c)
    )


def _apply_gamma(band: np.ndarray, params: ToneMapParams) -> np.ndarray:
    """Gamma-adjust with an offset to avoid crushing near-zero values."""
    offset_power = params.gamma_offset**params.gamma
    offset_range = (1 + params.gamma_offset) ** params.gamma - offset_power
    return (np.power(band + params.gamma_offset, params.gamma) - offset_power) / offset_range


def _modify_saturation(
    red: np.ndarray,
    green: np.ndarray,
    blue: np.ndarray,
    params: ToneMapParams,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Boost chroma by mixing away from the greyscale average."""
    grey = (red + green + blue) / 3.0
    base = grey * (1 - params.saturation)
    s = params.saturation
    return (
        np.clip(base + red * s, 0, 1.0),
        np.clip(base + green * s, 0, 1.0),
        np.clip(base + blue * s, 0, 1.0),
    )


def _linear_to_srgb(band: np.ndarray) -> np.ndarray:
    """sRGB opto-electronic transfer function."""
    return np.where(band <= 0.0031308, band * 12.92, 1.055 * np.power(band, 1.0 / 2.4) - 0.055)


def _stretch_band(band: np.ndarray, params: ToneMapParams = DEFAULT_TONE_MAP) -> np.ndarray:
    """Contrast-stretch and gamma-correct one band."""
    return _apply_gamma(
        _contrast_stretch_and_clip(
            band / SENTINEL_L3_MOSAIC_SCALE,
            params.middle_reflectance,
            1,
            params.maximum_reflectance,
        ),
        params,
    )


def true_color(
    red: np.ndarray,
    green: np.ndarray,
    blue: np.ndarray,
    params: ToneMapParams = DEFAULT_TONE_MAP,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Process Sentinel-2 L3 mosaic DN bands into true-color uint8 arrays."""
    r, g, b = _modify_saturation(
        _stretch_band(red, params),
        _stretch_band(green, params),
        _stretch_band(blue, params),
        params,
    )
    r, g, b = _linear_to_srgb(r), _linear_to_srgb(g), _linear_to_srgb(b)
    return (
        np.clip(r * 255, 0, 255).astype(np.ubyte),
        np.clip(g * 255, 0, 255).astype(np.ubyte),
        np.clip(b * 255, 0, 255).astype(np.ubyte),
    )


def process_bands(
    path_r: str,
    path_g: str,
    path_b: str,
    output_path: str,
    gdal_config: dict[str, str] | None = None,
) -> str:
    """Full-band load + windowed tone-map + write 4-band RGBA GeoTIFF from GDAL-compatible paths."""
    config = gdal_config or {}
    with gdal.config_options(config):
        ds_r = gdal.Open(path_r)
        ds_g = gdal.Open(path_g)
        ds_b = gdal.Open(path_b)
        if ds_r is None or ds_g is None or ds_b is None:
            raise RuntimeError(f"Cannot open source bands: {path_r}, {path_g}, {path_b}")

        gt = ds_r.GetGeoTransform()
        proj = ds_r.GetProjection()
        x_size = ds_r.RasterXSize
        y_size = ds_r.RasterYSize

        red_full = ds_r.GetRasterBand(1).ReadAsArray().astype(np.float32)
        green_full = ds_g.GetRasterBand(1).ReadAsArray().astype(np.float32)
        blue_full = ds_b.GetRasterBand(1).ReadAsArray().astype(np.float32)
        ds_r = ds_g = ds_b = None

        with gdal.GetDriverByName("GTiff").Create(
            output_path,
            x_size,
            y_size,
            4,
            gdal.GDT_Byte,
            # options=["COMPRESS=ZSTD", "ZSTD_LEVEL=18", "PREDICTOR=2"],
        ) as out_ds:
            out_ds.SetGeoTransform(gt)
            out_ds.SetProjection(proj)
            out_ds.GetRasterBand(4).SetColorInterpretation(gdal.GCI_AlphaBand)

            for y_off in range(0, y_size, _WINDOW_PIXELS):
                win_h = min(_WINDOW_PIXELS, y_size - y_off)
                for x_off in range(0, x_size, _WINDOW_PIXELS):
                    win_w = min(_WINDOW_PIXELS, x_size - x_off)

                    red = red_full[y_off : y_off + win_h, x_off : x_off + win_w]
                    green = green_full[y_off : y_off + win_h, x_off : x_off + win_w]
                    blue = blue_full[y_off : y_off + win_h, x_off : x_off + win_w]

                    alpha = np.where(
                        (red != 0) | (green != 0) | (blue != 0), np.uint8(255), np.uint8(0)
                    )
                    r, g, b = _modify_saturation(
                        _stretch_band(red),
                        _stretch_band(green),
                        _stretch_band(blue),
                        DEFAULT_TONE_MAP,
                    )
                    r, g, b = _linear_to_srgb(r), _linear_to_srgb(g), _linear_to_srgb(b)

                    out_ds.GetRasterBand(1).WriteArray(
                        np.clip(r * 255, 0, 255).astype(np.ubyte), x_off, y_off
                    )
                    out_ds.GetRasterBand(2).WriteArray(
                        np.clip(g * 255, 0, 255).astype(np.ubyte), x_off, y_off
                    )
                    out_ds.GetRasterBand(3).WriteArray(
                        np.clip(b * 255, 0, 255).astype(np.ubyte), x_off, y_off
                    )
                    out_ds.GetRasterBand(4).WriteArray(alpha, x_off, y_off)

    return output_path


def process_tile(tile: MosaicTile, output_path: str) -> str:
    """Read R/G/B bands for a tile, write 4-band RGBA GeoTIFF."""
    logger.info("Processing tile %s", tile.tile_id)
    path_r = _resolve_gdal_path(tile.href_red)
    path_g = _resolve_gdal_path(tile.href_green)
    path_b = _resolve_gdal_path(tile.href_blue)
    config: dict[str, str] = {}
    if path_r.startswith("/vsis3/"):
        config["AWS_VIRTUAL_HOSTING"] = "FALSE"
    process_bands(path_r, path_g, path_b, output_path, config)
    logger.info("Tile output written: %s", output_path)
    return output_path
