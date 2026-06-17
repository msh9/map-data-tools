# faa-static-data

Standalone script utility for converting FAA-provided static data into GeoJSON. Not a Poetry package — uses a plain Python virtual environment.

## Environment setup

```bash
python3 -m venv .venv
source .venv/bin/activate
```

## Convert sectional coverage file to GeoJSON

Converts the FAA sectional chart coverage text file into GeoJSON polygon features.

Emit a single combined file:

```bash
python convert_faa_sectional_coverage.py \
  --input ../../shared-configuration/faa-sectional-coverage.txt \
  --output ../../shared-configuration/faa-sectional-coverage.geojson
```

Emit one file per chart into the sectional mask directory:

```bash
python convert_faa_sectional_coverage.py \
  --input ../../shared-configuration/faa-sectional-coverage.txt \
  --coverage-dir ../../shared-configuration/sectional-chart-masks
```

The `--coverage-dir` form is the expected production usage — all downstream applications consume the per-chart mask files in `shared-configuration/sectional-chart-masks/`.

Note: the generated masks have been manually QA'd and corrected in QGIS. Re-running this script regenerates the raw output and will overwrite any manual corrections. Only re-run if the source coverage data changes, and re-verify masks in QGIS afterward.

## Tests

```bash
python -m unittest discover -s tests -p "test_*.py"
```
