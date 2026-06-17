# sentinel-mosaic

Build true-color COG mosaics from CDSE Sentinel-2 quarterly global mosaics
(`sentinel-2-global-mosaics` collection) for the raster-tilemaker pipeline.

General processing pipeline: STAC search →
fetch B04/B03/B02 → contrast stretch + gamma + saturation + sRGB OETF → uint8
RGBA → warp/clip into a per-region lossless webp COG. No scene selection by cloud
cover, no pan-sharpening. The tone-mapping pipeline reproduces the Sentinel
Hub reference script at
<https://custom-scripts.sentinel-hub.com/sentinel2-quarterly-cloudless-mosaic/true-color/>.

## Input: clip regions GeoJSON

`--clip-regions` expects a GeoJSON `FeatureCollection` where each feature has
a `region-name` property (string). One COG is produced per region per
quarter. Example:

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "properties": { "region-name": "salt-lake-mountains" },
      "geometry": { "type": "Polygon", "coordinates": [ ... ] }
    }
  ]
}
```

The `region-name` value is used verbatim in output filenames and in the
GDAL cutline filter during finalization, so prefer filesystem- and
SQL-safe names (no quotes, no slashes).

## Auth

Credentials are *access key / secret* pairs created on the [Copernicus Data
Space portal](https://documentation.dataspace.copernicus.eu/APIs/S3.html) —
not AWS IAM credentials. CDSE exposes an S3-compatible endpoint but uses
path-style addressing; the code sets `AWS_VIRTUAL_HOSTING=FALSE`
automatically.

Set two environment variables before running:

```
export AWS_S3_ENDPOINT=eodata.dataspace.copernicus.eu
export CPL_AWS_CREDENTIALS_FILE=/path/to/credentials
```

The credentials file must use AWS-style format (not the format shown on the
Copernicus page):

```ini
[default]
aws_access_key_id=YOUR_KEY
aws_secret_access_key=YOUR_SECRET
```

## Usage

```
AWS_S3_ENDPOINT=eodata.dataspace.copernicus.eu CPL_AWS_CREDENTIALS_FILE=[your file path] sentinel-mosaic \
  --clip-regions mountainous-regions.geojson \
  --output-dir ./out \
  --scratch-dir /var/tmp/sentinel-mosaic \
  --quarter 2024-Q3 \
```

One COG per quarter per region is emitted as
`{region}_{quarter}_sentinel.cog.tif`, plus one VRT per quarter named
`{quarter}-sentinel-mosaic.vrt`. There is no merging across quarters.

### `--output-dir` vs. `--scratch-dir`

`--output-dir` holds the finalized COGs and VRTs only — write-once, read-mostly
artifacts safe to point at a network-mounted artifact store (GCS Fuse, NFS).

`--scratch-dir` holds the per-region accumulator (`{region}_{quarter}_accumulator.tif`)
which receives heavy random-access read+write traffic during tile accumulation;
point it at local SSD, never a network mount. If `--scratch-dir` is omitted a
per-run temp directory is created and removed at exit. Pass an explicit path
when you want resume-after-crash semantics across runs.

### Parallelism

By default the pipeline is fully serial (`--workers 1`). Pass `--workers N` to
fetch + tone-map up to `N` tiles concurrently while the main thread writes to
the accumulator. On a 2-vCPU host, `--workers 2` overlaps CDSE band fetches and
tone-mapping with accumulator writes, reliably using both cores. Drain order
still matches submission order, so the "first tile wins" alpha-overlay rule
produces identical pixels regardless of worker count.

GDAL warp and COG compression are also configured to multi-thread. The default
thread budget matches `--workers`; override via `SENTINEL_MOSAIC_GDAL_NUM_THREADS`
if you need a different value (e.g. to allocate more threads to compression
without growing the producer pool).

### Iterating on tone-mapping without re-querying STAC

STAC discovery is the slow part of each run. Two flags let you cache the
search results and iterate on the raster pipeline only:

```
# First run: query STAC and save the tile list, skipping imagery fetch.
sentinel-mosaic --clip-regions regions.geojson --output-dir ./out \
    --quarter 2024-Q3 --save-scenes scenes.json

# Subsequent runs: reuse the cached tile list, skipping STAC.
sentinel-mosaic --clip-regions regions.geojson --output-dir ./out \
    --quarter 2024-Q3 --load-scenes scenes.json
```

`--save-scenes` and `--load-scenes` are mutually exclusive.

## Processing pipeline internals

Each tile goes through three sequential stages:

### 1. Band fetch and tone-mapping (`process_bands`)

`process_bands` opens the three GDAL-compatible band paths (R=B04, G=B03, B=B02)
and writes a 4-band RGBA GeoTIFF to a GDAL `/vsimem/` in-memory path. It reads
and processes data in `_WINDOW_PIXELS=2048` row-strips to cap working-set memory.

Within each strip the tone-mapping pipeline runs in order:

1. **DN → reflectance** — divide by `SENTINEL_L3_MOSAIC_SCALE=10000`.
2. **Sigmoidal contrast stretch** (`_contrast_stretch_and_clip`) — compresses the
   dynamic range around `middle_reflectance=0.13` with `maximum_reflectance=3.0`.
3. **Gamma** (`_apply_gamma`) — `γ=1.8` with a small offset (`0.01`) to avoid
   crushing near-zero values.
4. **Saturation boost** (`_modify_saturation`) — mixes each channel away from the
   greyscale mean by a factor of `1.15`.
5. **sRGB OETF** (`_linear_to_srgb`) — the standard electro-optical transfer
   function. Note: applied after gamma, matching the Sentinel Hub reference script
   exactly rather than a principled color pipeline.
6. **uint8 quantization** — `np.clip(× 255, 0, 255).astype(np.ubyte)`.

Alpha is set to 255 wherever any source band is non-zero.

### 2. Warp and clip (`finalize_output_tile`)

`gdal.Warp` reprojects the in-memory RGBA TIFF to `ESRI:102009` (Lambert
Azimuthal Equal-Area, North America), clips to the region's cutline polygon, and
writes a COG with WEBP lossless compression and 512-pixel tiles.

### 3. VRT assembly (`build_per_region_vrt`, `build_top_level_vrt`)

Per-region VRTs mosaic the tile COGs (last STAC tile wins on overlap, achieved by
reversing the source list since GDAL VRT is first-source-wins). A top-level
VRT-of-VRTs references all per-region VRTs for the quarter.

## Development setup

```bash
poetry install
poetry run pytest        # run all tests
poetry run ruff check .  # lint
```

GDAL must be available system-wide with JXL codec support and the
`vsis3`/`vsicurl` virtual filesystem drivers enabled. The CLI sets
`GDAL_CACHEMAX=2048` (MiB) at startup to keep per-tile reads in memory.
considerations.

Tests are self-contained and do not require CDSE credentials or network
access. They cover: CLI argument parsing, STAC search mocking, tone-mapping
correctness (including a golden-value regression test), per-tile RGBA output,
and accumulator accumulate/finalize round-trips.
