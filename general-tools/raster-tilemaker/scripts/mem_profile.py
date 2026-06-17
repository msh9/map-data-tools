from __future__ import annotations

import resource
import sys
import threading
import time
import tracemalloc
from pathlib import Path

from osgeo import gdal

gdal.UseExceptions()

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from raster_tilemaker.grid import tile_index_range  # noqa: E402
from raster_tilemaker.pipeline import build_mosaic_output  # noqa: E402
from raster_tilemaker.render.mosaic import read_vrt_metadata  # noqa: E402

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "tests/fixtures/e2e/source"
TILE_SIZE = 512


def kb_to_mb(kb: int) -> float:
    return kb / 1024.0


class RSSSampler(threading.Thread):
    """Polls process RSS to capture native (GDAL/numpy/PIL) peak, not just Python heap."""

    def __init__(self, interval: float = 0.01) -> None:
        super().__init__(daemon=True)
        self.interval = interval
        self.peak_kb = 0
        self._stop = threading.Event()

    def _rss_kb(self) -> int:
        # children RSS is reported separately; sum self + children for the parallel path
        rs = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        ch = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
        return rs + ch

    def run(self) -> None:
        while not self._stop.is_set():
            self.peak_kb = max(self.peak_kb, self._rss_kb())
            time.sleep(self.interval)

    def stop(self) -> int:
        self._stop.set()
        self.join()
        return max(self.peak_kb, self._rss_kb())


def build_vrt(vrt_path: Path) -> None:
    tifs = sorted(str(p) for p in FIXTURE_DIR.glob("*.tif"))
    print(f"  source tifs: {[Path(t).name for t in tifs]}")
    gdal.BuildVRT(str(vrt_path), tifs)


def count_tiles(vrt_path: Path, resolutions: list[float]) -> int:
    meta = read_vrt_metadata(vrt_path)
    min_x, _, _, max_y = meta.bounds
    origin = (min_x, max_y)
    total = 0
    for res in resolutions:
        x0, y0, x1, y1 = tile_index_range(meta.bounds, origin, res, TILE_SIZE)
        n = (x1 - x0 + 1) * (y1 - y0 + 1)
        total += n
        print(f"    res={res:>6} m/px  grid={x1 - x0 + 1}x{y1 - y0 + 1}  tiles={n}")
    print(f"    TOTAL tile specs = {total}")
    return total


def profile_run(label: str, vrt_path: Path, out_dir: Path, resolutions: list[float], workers: int | None) -> None:
    print(f"\n=== {label} (workers={workers}) ===")
    out_dir.mkdir(parents=True, exist_ok=True)
    sampler = RSSSampler()
    tracemalloc.start()
    base_rss = sampler._rss_kb()
    sampler.start()
    t0 = time.time()
    build_mosaic_output(
        vrt_path,
        out_dir,
        resolutions,
        tile_size=TILE_SIZE,
        quality=30,
        tile_format="webp",
        output_kind="pmtiles",
        pmtiles_file=Path(f"{label}.pmtiles"),
        render_workers=workers,
    )
    elapsed = time.time() - t0
    peak_py_bytes = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    peak_rss = sampler.stop()
    archive = out_dir / f"{label}.pmtiles"
    size = archive.stat().st_size if archive.exists() else 0
    print(f"  elapsed:            {elapsed:6.1f} s")
    print(f"  RSS at start:       {kb_to_mb(base_rss):8.1f} MB")
    print(f"  peak RSS (self+ch): {kb_to_mb(peak_rss):8.1f} MB  (delta {kb_to_mb(peak_rss - base_rss):+.1f} MB)")
    print(f"  peak Python heap:   {peak_py_bytes / 1048576:8.1f} MB  (tracemalloc, main proc only)")
    print(f"  output archive:     {size / 1024:8.1f} KB")


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--resolutions", default="640,320,160,80,40")
    parser.add_argument("--mode", choices=("serial", "parallel", "both"), default="both")
    parser.add_argument("--workers", type=int, default=0)
    args = parser.parse_args()
    resolutions = [float(r) for r in args.resolutions.split(",")]

    work = Path("/tmp/rtm_memprofile")
    work.mkdir(parents=True, exist_ok=True)
    vrt_path = work / "mosaic.vrt"
    print("Building VRT from fixtures...")
    build_vrt(vrt_path)
    print("Tile counts for resolutions", resolutions, ":")
    count_tiles(vrt_path, resolutions)

    if args.mode in ("serial", "both"):
        profile_run("serial", vrt_path, work / "serial", resolutions, workers=1)
    if args.mode in ("parallel", "both"):
        w = args.workers if args.workers > 0 else None
        profile_run("parallel", vrt_path, work / "parallel", resolutions, workers=w)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
