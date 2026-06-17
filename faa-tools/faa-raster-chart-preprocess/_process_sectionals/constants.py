from __future__ import annotations

import os

DEFAULT_MOSAIC_FILE_MATCH_TOKEN = ".clip."

TARGET_CRS = "ESRI:102009"
DEFAULT_THREADS = max(1, os.cpu_count() or 1)

FULL_CHART_COG_OPTIONS = [
    "COMPRESS=WEBP",
    "QUALITY=40",
    "BLOCKSIZE=512",
]

CLIPPED_CHART_COG_OPTIONS_ZSTD = [
    "COMPRESS=ZSTD",
    "PREDICTOR=2",
    # COG uses LEVEL for ZSTD compression level.
    "LEVEL=20",
    "BLOCKSIZE=512",
]

CLIPPED_CHART_COG_OPTIONS_JXL_LOSSLESS = [
    "COMPRESS=JXL",
    "JXL_LOSSLESS=YES",
    "JXL_EFFORT=7",
    "BLOCKSIZE=512",
]

CLIPPED_OUTPUT_MODE_ZSTD = "zstd"
CLIPPED_OUTPUT_MODE_JXL_LOSSLESS = "jxl-lossless"
DEFAULT_CLIPPED_OUTPUT_MODE = CLIPPED_OUTPUT_MODE_ZSTD

CHART_TYPE_SECTIONAL = "sectional"
CHART_TYPE_TAC = "tac"
CHART_TYPE_FLY = "fly"
CHART_TYPES = (CHART_TYPE_SECTIONAL, CHART_TYPE_TAC, CHART_TYPE_FLY)
MAPPING_KEY_BY_CHART_TYPE = {
    CHART_TYPE_SECTIONAL: "sectional",
    CHART_TYPE_TAC: "terminal_area",
    CHART_TYPE_FLY: "terminal_area",
}

TERMINAL_AREA_KEY_ALIASES = {
    "dallasfortworth": ("dallasftworth",),
    "dallasftworth": ("dallasfortworth",),
    "sanjuan": ("puertoricovi", "puertoricovitac"),
    "puertoricovi": ("sanjuan",),
    "puertoricovitac": ("sanjuan",),
}

# FAA TAC package files that should not be processed as TAC/FLY chart outputs.
TAC_SKIP_FILENAMES = {
    "anchorage graphic.tif",
    "caribbean planning chart.tif",
    "new york tac vfr planning charts.tif",
}

# FAA sectional package files that are intentionally excluded for now.
SECTIONAL_SKIP_FILENAMES = {
    "honolulu inset sec.tif",
}
