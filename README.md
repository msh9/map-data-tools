# tilemaker

Collection of map data transformation utilities for GIS / map data. Each subdirectory is an independent application or shared library. See each folder's `README.md` for full usage and development details. The repository is split into two folders. One, tools that are specific to aviation and US FAA data, `faa-tools`. Two, tools that are more general and handle various types of raster or vector GIS data for mapping.

## Utilities

### raster-tilemaker
Converts a GDAL VRT mosaic into tiled raster outputs (ZXY directory layout or PMTiles archive). Requires GDAL Python bindings. Feeds the web-tilelayer raster map layer.

### vector-tilemaker
Produces vector tile PMTiles archives from GeoJSON inputs via tippecanoe. Used to package navaid and obstacle data for the web-tilelayer vector layer.

### faa-raster-chart-preprocess
Converts FAA VFR chart GeoTIFFs (sectional, TAC, FLY) into Cloud Optimized GeoTIFFs (WEBP full + ZSTD/JXL clipped) and assembles per-region VRT mosaics for `raster-tilemaker`.

### faa-vfr-fetch
Downloads and extracts FAA VFR chart GeoTIFF packages (sectional and TAC) from aeronav.faa.gov, with automatic cycle detection and a fetch manifest output.

### nasr-aixm2geojson
Parses FAA NASR AIXM 5.1 XML navigation aid records into gzip-compressed GeoJSON point features (WGS84 or ESRI:102009).

### dof2geojson
Converts FAA Digital Obstacle File (DOF) fixed-width text records into gzip-compressed GeoJSON point features (WGS84 or ESRI:102009), with optional per-state filtering.

### sentinel-mosaic
Builds true-color COG mosaics from CDSE Sentinel-2 quarterly global mosaics, applying contrast stretch + sRGB tone mapping, clipped to mountainous regions for `raster-tilemaker`.

### dem-2-slope
Converts USGS 3DEP 1-arc-second DEM GeoTIFFs into slope-shaded 2-band LA COGs (luminance + alpha, ZSTD) clipped to mountainous regions, with VRT mosaic output for `raster-tilemaker`.

### faa-static-data
Standalone script utility (not a Poetry package) for converting the FAA sectional chart coverage text file into GeoJSON polygon masks. Output masks are committed into `shared-configuration/`.

### tilemaker-shared
Shared Python library consumed as a path dependency by `dof2geojson` and `nasr-aixm2geojson`. Provides GeoJSON streaming writer, ESRI:102009 coordinate transform, and related helpers. Not a standalone application.

### shared-configuration
Static configuration files consumed by multiple utilities: FAA chart region mapping, sectional chart coverage masks, TAC/FLY chart masks, mountainous region polygon definitions, and USGS DEM URL lists.

### tac-static-data
Proof-of-concept heuristic TAC chart mask generator. **Inactive** — hand-generated masks in `shared-configuration/terminal-area-fly-chart-masks/` are used in production. Preserved for reference.

---

## Third-party tools

External GIS tooling is stored in `general-tools/third-party-tools/` so binaries stay out of git while remaining visible and easy to script.

### Tippecanoe setup

`tippecanoe` is pinned in `third-party-tools.lock.json` and installed by:

```bash
python3 scripts/setup_third_party_tools.py --tool tippecanoe
```

Install output is written under:

```text
third-party-tools/tippecanoe/<version>/bin/
```

Current pinned version binary path:

```text
third-party-tools/tippecanoe/2.79.0/bin/tippecanoe
```

The setup script builds from source (`https://github.com/felt/tippecanoe`) and requires `git` and `make`. On Linux, tippecanoe upstream documents these typical build deps: `gcc g++ make libsqlite3-dev zlib1g-dev`.

Examples:

```bash
# Verify install
third-party-tools/tippecanoe/2.79.0/bin/tippecanoe --version

# Add to PATH in current shell session
export PATH="$PWD/third-party-tools/tippecanoe/2.79.0/bin:$PATH"
```

PowerShell (current session):

```powershell
$env:Path = "$PWD/third-party-tools/tippecanoe/2.79.0/bin;$env:Path"
```

### PMTiles CLI setup

`pmtiles` (from `protomaps/go-pmtiles` release binaries) is also pinned in `third-party-tools.lock.json` and installed by:

```bash
python3 scripts/setup_third_party_tools.py --tool pmtiles
```

Install output is written under:

```text
third-party-tools/pmtiles/<version>/bin/
```

Current pinned version binary paths:

```text
third-party-tools/pmtiles/1.30.0/bin/pmtiles
third-party-tools/pmtiles/1.30.0/bin/pmtiles.exe
```

The setup script downloads the pinned release archive for your current platform/architecture (`linux|darwin|windows`, `x86_64|arm64`), verifies its SHA-256 checksum from the lock file, and installs the extracted binary.

Examples:

```bash
# Verify install (Linux/macOS)
third-party-tools/pmtiles/1.30.0/bin/pmtiles version

# Verify install (PowerShell / Windows)
.\third-party-tools\pmtiles\1.30.0\bin\pmtiles.exe version
```

To install all pinned tools in one run:

```bash
python3 scripts/setup_third_party_tools.py --tool all
```

## Working in this repo

Run tooling from the application directory you are changing.

Example:

```bash
cd raster-tilemaker
poetry install
poetry run raster-tilemaker build-tiles --input-vrt /path/to/mosaic.vrt
poetry run pytest
poetry run ruff check .
```
