DEFAULT_TILE_SIZE = 512
DEFAULT_QUALITY = 30
DEFAULT_FORMAT = "webp"
TARGET_CRS = "ESRI:102009"
TILE_CONFIG_NAME = "tile_config.json"
# ESRI:102009 projected extent from adr/ADR-002 Raster Tiling.md
ESRI_102009_EXTENT = (-6698991.38, -1707869.78, 4576959.89, 6243265.5)
# ADR-005 default resolution ladder (meters per pixel), coarse to fine.
DEFAULT_RESOLUTIONS = [2560, 1280, 640, 320, 160, 80, 40, 20]


def esri_102009_origin() -> tuple[float, float]:
    min_x, _, _, max_y = ESRI_102009_EXTENT
    return (min_x, max_y)
