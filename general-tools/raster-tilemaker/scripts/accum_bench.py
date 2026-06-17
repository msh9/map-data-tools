"""Isolate the count-scaled accumulator cost: the _Entry / _PendingTile lists
plus the parallel path's tile_specs list and all-futures-upfront dict."""
from __future__ import annotations

import sys
import tracemalloc
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from raster_tilemaker.output.pmtiles import _Entry, _PendingTile  # noqa: E402


def measure(label: str, build) -> None:
    tracemalloc.start()
    obj = build()
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    n = len(obj)
    print(f"{label:32} N={n:>9,}  peak={peak/1048576:8.1f} MB  per-item={peak/n:6.1f} B")
    del obj


N = 1_000_000

# Current frozen dataclass (has __dict__, no __slots__)
measure("_Entry list (current)", lambda: [
    _Entry(tile_id=i * 7, offset=i * 4096, length=4096, run_length=1) for i in range(N)
])
measure("_PendingTile list (current)", lambda: [
    _PendingTile(local_z=i % 8, x=i, y=i, offset=i * 4096, length=4096) for i in range(N)
])

# tile_specs list materialized upfront in the parallel path
measure("tile_specs tuples (parallel)", lambda: [
    (i % 8, i, i, (float(i), float(i), float(i + 1), float(i + 1))) for i in range(N)
])


# What __slots__ would save
class EntrySlots:
    __slots__ = ("tile_id", "offset", "length", "run_length")

    def __init__(self, tile_id, offset, length, run_length):
        self.tile_id = tile_id
        self.offset = offset
        self.length = length
        self.run_length = run_length


measure("_Entry list WITH __slots__", lambda: [
    EntrySlots(i * 7, i * 4096, 4096, 1) for i in range(N)
])
