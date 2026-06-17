from __future__ import annotations

import functools
import gzip
import io
import json
import logging
import os
import shutil
import tempfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Iterable

from raster_tilemaker.render.mosaic import RenderedTile, ensure_format_support

logger = logging.getLogger(__name__)


class _Compression(IntEnum):
    UNKNOWN = 0
    NONE = 1
    GZIP = 2
    BROTLI = 3
    ZSTD = 4


class _TileType(IntEnum):
    UNKNOWN = 0
    MVT = 1
    PNG = 2
    JPEG = 3
    WEBP = 4
    AVIF = 5
    MLT = 6


@dataclass(frozen=True)
class _Entry:
    tile_id: int
    offset: int
    length: int
    run_length: int


@dataclass(frozen=True)
class _PendingTile:
    local_z: int
    x: int
    y: int
    offset: int
    length: int


def _rotate(n: int, x: int, y: int, rx: int, ry: int) -> tuple[int, int]:
    if ry == 0:
        if rx != 0:
            x = n - 1 - x
            y = n - 1 - y
        x, y = y, x
    return x, y


def _zxy_to_tile_id(z: int, x: int, y: int) -> int:
    if z > 31:
        raise ValueError("Tile zoom exceeds PMTiles 64-bit limit.")
    max_index = (1 << z) - 1
    if x < 0 or y < 0 or x > max_index or y > max_index:
        raise ValueError("Tile x/y outside zoom level bounds.")

    acc = ((1 << (z * 2)) - 1) // 3
    level = z - 1
    tile_x = x
    tile_y = y
    while level >= 0:
        step = 1 << level
        rx = step & tile_x
        ry = step & tile_y
        acc += ((3 * rx) ^ ry) << level
        tile_x, tile_y = _rotate(step, tile_x, tile_y, rx, ry)
        level -= 1
    return acc


def _write_varint(buffer: io.BytesIO, value: int) -> None:
    current = value
    while True:
        to_write = current & 0x7F
        current >>= 7
        if current:
            buffer.write(bytes([to_write | 0x80]))
        else:
            buffer.write(bytes([to_write]))
            break


def _serialize_directory(entries: list[_Entry]) -> bytes:
    if not entries:
        raise ValueError("PMTiles directory entries cannot be empty.")

    buffer = io.BytesIO()
    _write_varint(buffer, len(entries))

    last_tile_id = 0
    for entry in entries:
        _write_varint(buffer, entry.tile_id - last_tile_id)
        last_tile_id = entry.tile_id

    for entry in entries:
        _write_varint(buffer, entry.run_length)

    for entry in entries:
        _write_varint(buffer, entry.length)

    for index, entry in enumerate(entries):
        if index > 0:
            prev = entries[index - 1]
            if entry.offset == prev.offset + prev.length:
                _write_varint(buffer, 0)
                continue
        _write_varint(buffer, entry.offset + 1)

    return gzip.compress(buffer.getvalue())


def _build_roots_leaves(entries: list[_Entry], leaf_size: int) -> tuple[bytes, bytes]:
    root_entries: list[_Entry] = []
    leaves_bytes = b""

    index = 0
    while index < len(entries):
        leaf_entries = entries[index : index + leaf_size]
        leaf_data = _serialize_directory(leaf_entries)
        root_entries.append(
            _Entry(
                tile_id=leaf_entries[0].tile_id,
                offset=len(leaves_bytes),
                length=len(leaf_data),
                run_length=0,
            )
        )
        leaves_bytes += leaf_data
        index += leaf_size

    return _serialize_directory(root_entries), leaves_bytes


def _optimize_directories(entries: list[_Entry], target_root_length: int) -> tuple[bytes, bytes]:
    root = _serialize_directory(entries)
    if len(root) < target_root_length:
        return root, b""

    leaf_size = 4096
    while True:
        root, leaves = _build_roots_leaves(entries, leaf_size)
        if len(root) < target_root_length:
            return root, leaves
        leaf_size *= 2


def _serialize_header(header: dict[str, int]) -> bytes:
    buffer = io.BytesIO()

    def write_uint64(value: int) -> None:
        buffer.write(value.to_bytes(8, byteorder="little", signed=False))

    def write_int32(value: int) -> None:
        buffer.write(value.to_bytes(4, byteorder="little", signed=True))

    def write_uint8(value: int) -> None:
        buffer.write(value.to_bytes(1, byteorder="little", signed=False))

    buffer.write(b"PMTiles")
    buffer.write(b"\x03")
    write_uint64(header["root_offset"])
    write_uint64(header["root_length"])
    write_uint64(header["metadata_offset"])
    write_uint64(header["metadata_length"])
    write_uint64(header["leaf_directory_offset"])
    write_uint64(header["leaf_directory_length"])
    write_uint64(header["tile_data_offset"])
    write_uint64(header["tile_data_length"])
    write_uint64(header["addressed_tiles_count"])
    write_uint64(header["tile_entries_count"])
    write_uint64(header["tile_contents_count"])
    write_uint8(1 if header["clustered"] else 0)
    write_uint8(_Compression.GZIP)
    write_uint8(_Compression.NONE)
    write_uint8(header["tile_type"])
    write_uint8(header["min_zoom"])
    write_uint8(header["max_zoom"])
    write_int32(header["min_lon_e7"])
    write_int32(header["min_lat_e7"])
    write_int32(header["max_lon_e7"])
    write_int32(header["max_lat_e7"])
    write_uint8(header["center_zoom"])
    write_int32(header["center_lon_e7"])
    write_int32(header["center_lat_e7"])

    raw = buffer.getvalue()
    if len(raw) != 127:
        raise ValueError(f"Invalid PMTiles header length: expected 127, got {len(raw)}")
    return raw


def _encode_tile(tile: RenderedTile, *, tile_format: str, quality: int) -> bytes:
    from PIL import Image

    tile_array = tile.tile_array
    if getattr(tile_array, "ndim", None) != 3 or tile_array.shape[2] not in {2, 3, 4}:
        raise ValueError("Rendered tile array must be HxWx2, HxWx3, or HxWx4 uint8 data.")
    channels = tile_array.shape[2]
    if channels == 2:
        mode = "LA"
    elif channels == 4:
        mode = "RGBA"
    else:
        mode = "RGB"
    image = Image.fromarray(tile_array, mode=mode)
    encoded = io.BytesIO()
    image.save(encoded, format=tile_format.upper(), quality=quality)
    return encoded.getvalue()


def _tile_type_for_format(tile_format: str) -> int:
    if tile_format == "webp":
        return _TileType.WEBP
    if tile_format == "avif":
        return _TileType.AVIF
    if tile_format == "png":
        return _TileType.PNG
    raise ValueError(f"Unsupported PMTiles raster format: {tile_format}")


def _required_pmtiles_zoom(local_z: int, x: int, y: int) -> int:
    max_index = max(x, y)
    return max(local_z, max_index.bit_length())


def _write_pmtiles_file(
    entries: list[_Entry],
    tile_count: int,
    min_zoom: int | None,
    max_zoom: int | None,
    metadata_obj: dict,
    bounds_wgs84: tuple[float, float, float, float],
    tile_format: str,
    tile_data_file,
    tile_data_length: int,
    output_file: Path,
    max_required_zoom_offset: int,
    pmtiles_zoom_by_local: dict[int, int],
) -> int:
    """Assemble and write a PMTiles archive from pre-built entries and tile data."""
    metadata_with_debug = dict(metadata_obj)
    metadata_with_debug["localZoomToPmtilesZoom"] = {
        str(local_z): pmtiles_z for local_z, pmtiles_z in sorted(pmtiles_zoom_by_local.items())
    }
    metadata_with_debug["pmtilesZoomOffset"] = max_required_zoom_offset

    sorted_entries = sorted(entries, key=lambda entry: entry.tile_id)
    root_dir, leaf_dirs = _optimize_directories(sorted_entries, 16384 - 127)
    metadata_bytes = gzip.compress(json.dumps(metadata_with_debug).encode("utf-8"))

    logger.info(
        "PMTiles directory optimized",
        extra={
            "entry_count": len(sorted_entries),
            "root_dir_bytes": len(root_dir),
            "leaf_dirs_bytes": len(leaf_dirs),
        },
    )

    min_lon, min_lat, max_lon, max_lat = bounds_wgs84
    center_lon = (min_lon + max_lon) / 2.0
    center_lat = (min_lat + max_lat) / 2.0

    header = {
        "root_offset": 127,
        "root_length": len(root_dir),
        "metadata_offset": 127 + len(root_dir),
        "metadata_length": len(metadata_bytes),
        "leaf_directory_offset": 127 + len(root_dir) + len(metadata_bytes),
        "leaf_directory_length": len(leaf_dirs),
        "tile_data_offset": 127 + len(root_dir) + len(metadata_bytes) + len(leaf_dirs),
        "tile_data_length": tile_data_length,
        "addressed_tiles_count": tile_count,
        "tile_entries_count": len(entries),
        "tile_contents_count": tile_count,
        "clustered": 0,
        "tile_type": _tile_type_for_format(tile_format),
        "min_zoom": int(min_zoom),
        "max_zoom": int(max_zoom),
        "min_lon_e7": int(min_lon * 10_000_000),
        "min_lat_e7": int(min_lat * 10_000_000),
        "max_lon_e7": int(max_lon * 10_000_000),
        "max_lat_e7": int(max_lat * 10_000_000),
        "center_zoom": int(min_zoom),
        "center_lon_e7": int(center_lon * 10_000_000),
        "center_lat_e7": int(center_lat * 10_000_000),
    }

    with output_file.open("wb") as output_stream:
        output_stream.write(_serialize_header(header))
        output_stream.write(root_dir)
        output_stream.write(metadata_bytes)
        output_stream.write(leaf_dirs)
        tile_data_file.seek(0)
        shutil.copyfileobj(tile_data_file, output_stream)

    logger.info(
        "PMTiles archive written",
        extra={
            "output_file": str(output_file),
            "tile_data_bytes": tile_data_length,
            "min_zoom": int(min_zoom),
            "max_zoom": int(max_zoom),
        },
    )
    return len(entries)


def write_pmtiles_archive(
    tiles: Iterable[RenderedTile],
    output_file: Path,
    *,
    tile_format: str,
    quality: int,
    resolutions: Iterable[float],
    bounds_wgs84: tuple[float, float, float, float],
    metadata: dict | None = None,
) -> int:
    ensure_format_support(tile_format)

    output_file.parent.mkdir(parents=True, exist_ok=True)

    logger.info(
        "Encoding tiles for PMTiles archive",
        extra={"output_file": str(output_file), "tile_format": tile_format, "quality": quality},
    )

    metadata_obj = metadata or {}
    pending_tiles: list[_PendingTile] = []
    tiles_skipped_empty = 0
    max_required_zoom_offset = 0
    resolution_list = list(resolutions)
    local_zoom_levels = list(range(len(resolution_list)))

    with tempfile.TemporaryFile() as tile_data_file:
        tile_data_length = 0
        for tile in tiles:
            if not tile.has_data:
                tiles_skipped_empty += 1
                continue

            encoded = _encode_tile(tile, tile_format=tile_format, quality=quality)
            pending_tiles.append(
                _PendingTile(
                    local_z=tile.z,
                    x=tile.x,
                    y=tile.y,
                    offset=tile_data_length,
                    length=len(encoded),
                )
            )
            tile_data_file.write(encoded)
            tile_data_length += len(encoded)

            required_zoom = _required_pmtiles_zoom(tile.z, tile.x, tile.y)
            max_required_zoom_offset = max(max_required_zoom_offset, required_zoom - tile.z)

        logger.info(
            "Tile encoding complete",
            extra={
                "tiles_written": len(pending_tiles),
                "tiles_skipped_empty": tiles_skipped_empty,
                "tile_data_bytes": tile_data_length,
            },
        )

        if not pending_tiles:
            logger.warning(
                "No non-empty tiles were generated; refusing to write an empty PMTiles archive",
                extra={"output_file": str(output_file)},
            )
            raise ValueError(
                "No non-empty tiles were generated; refusing to write an empty PMTiles archive."
            )

        pmtiles_zoom_by_local = {
            local_z: local_z + max_required_zoom_offset for local_z in local_zoom_levels
        }
        for pmtiles_z in pmtiles_zoom_by_local.values():
            if pmtiles_z > 31:
                raise ValueError("PMTiles zoom exceeds supported limit (31).")

        logger.info(
            "PMTiles zoom mapping computed",
            extra={
                "zoom_offset": max_required_zoom_offset,
                "local_to_pmtiles_zoom": {
                    str(lz): pz for lz, pz in sorted(pmtiles_zoom_by_local.items())
                },
            },
        )

        entries: list[_Entry] = []
        min_zoom: int | None = None
        max_zoom: int | None = None
        for tile in pending_tiles:
            if tile.local_z not in pmtiles_zoom_by_local:
                raise ValueError(f"No PMTiles zoom mapping found for local z={tile.local_z}.")
            pmtiles_z = pmtiles_zoom_by_local[tile.local_z]
            tile_id = _zxy_to_tile_id(pmtiles_z, tile.x, tile.y)
            entries.append(_Entry(tile_id=tile_id, offset=tile.offset, length=tile.length, run_length=1))
            if min_zoom is None or pmtiles_z < min_zoom:
                min_zoom = pmtiles_z
            if max_zoom is None or pmtiles_z > max_zoom:
                max_zoom = pmtiles_z

        return _write_pmtiles_file(
            entries,
            tile_count=len(pending_tiles),
            min_zoom=min_zoom,
            max_zoom=max_zoom,
            metadata_obj=metadata_obj,
            bounds_wgs84=bounds_wgs84,
            tile_format=tile_format,
            tile_data_file=tile_data_file,
            tile_data_length=tile_data_length,
            output_file=output_file,
            max_required_zoom_offset=max_required_zoom_offset,
            pmtiles_zoom_by_local=pmtiles_zoom_by_local,
        )


def write_pmtiles_archive_parallel(
    input_vrt: Path,
    output_file: Path,
    *,
    tile_format: str,
    quality: int,
    resolutions: Iterable[float],
    bounds_wgs84: tuple[float, float, float, float],
    aggregate_bounds: tuple[float, float, float, float],
    origin: tuple[float, float],
    band_count: int,
    tile_size: int,
    metadata: dict | None = None,
    render_workers: int | None = None,
) -> int:
    from raster_tilemaker.render.mosaic import (
        _worker_init,
        iter_tile_specs,
        render_and_encode_tile,
    )

    ensure_format_support(tile_format)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    _workers = render_workers if (render_workers is not None and render_workers > 0) else (os.cpu_count() or 1)
    resolution_list = list(resolutions)
    local_zoom_levels = list(range(len(resolution_list)))
    metadata_obj = metadata or {}

    # Enumerate all tile coordinates upfront — pure math, no GDAL.
    tile_specs = list(iter_tile_specs(aggregate_bounds, origin, resolution_list, tile_size))

    # Compute max_required_zoom_offset before any futures are submitted so that
    # pmtiles zoom levels can be assigned as results arrive out of order.
    max_required_zoom_offset = 0
    for z, x, y, _ in tile_specs:
        required_zoom = _required_pmtiles_zoom(z, x, y)
        max_required_zoom_offset = max(max_required_zoom_offset, required_zoom - z)

    pmtiles_zoom_by_local = {
        local_z: local_z + max_required_zoom_offset for local_z in local_zoom_levels
    }
    for pmtiles_z in pmtiles_zoom_by_local.values():
        if pmtiles_z > 31:
            raise ValueError("PMTiles zoom exceeds supported limit (31).")

    logger.info(
        "PMTiles zoom mapping computed",
        extra={
            "zoom_offset": max_required_zoom_offset,
            "local_to_pmtiles_zoom": {
                str(lz): pz for lz, pz in sorted(pmtiles_zoom_by_local.items())
            },
        },
    )
    logger.info(
        "Beginning parallel tile render+encode",
        extra={
            "output_file": str(output_file),
            "tile_format": tile_format,
            "quality": quality,
            "render_workers": _workers,
            "total_tile_specs": len(tile_specs),
        },
    )

    worker_fn = functools.partial(
        render_and_encode_tile,
        tile_size=tile_size,
        tile_format=tile_format,
        quality=quality,
    )

    entries: list[_Entry] = []
    tiles_skipped_empty = 0
    min_zoom: int | None = None
    max_zoom: int | None = None

    with tempfile.TemporaryFile() as tile_data_file:
        tile_data_length = 0

        with ProcessPoolExecutor(
            max_workers=_workers,
            initializer=_worker_init,
            initargs=(str(input_vrt), band_count),
        ) as executor:
            futures = {
                executor.submit(worker_fn, tile_bounds, z, x, y): None
                for z, x, y, tile_bounds in tile_specs
            }
            for future in as_completed(futures):
                result_z, result_x, result_y, has_data, encoded = future.result()
                if not has_data:
                    tiles_skipped_empty += 1
                    continue

                offset = tile_data_length
                tile_data_file.write(encoded)
                tile_data_length += len(encoded)

                pmtiles_z = pmtiles_zoom_by_local[result_z]
                tile_id = _zxy_to_tile_id(pmtiles_z, result_x, result_y)
                entries.append(
                    _Entry(tile_id=tile_id, offset=offset, length=len(encoded), run_length=1)
                )
                if min_zoom is None or pmtiles_z < min_zoom:
                    min_zoom = pmtiles_z
                if max_zoom is None or pmtiles_z > max_zoom:
                    max_zoom = pmtiles_z

        logger.info(
            "Parallel tile render+encode complete",
            extra={
                "tiles_written": len(entries),
                "tiles_skipped_empty": tiles_skipped_empty,
                "tile_data_bytes": tile_data_length,
            },
        )

        if not entries:
            logger.warning(
                "No non-empty tiles were generated; refusing to write an empty PMTiles archive",
                extra={"output_file": str(output_file)},
            )
            raise ValueError(
                "No non-empty tiles were generated; refusing to write an empty PMTiles archive."
            )

        return _write_pmtiles_file(
            entries,
            tile_count=len(entries),
            min_zoom=min_zoom,
            max_zoom=max_zoom,
            metadata_obj=metadata_obj,
            bounds_wgs84=bounds_wgs84,
            tile_format=tile_format,
            tile_data_file=tile_data_file,
            tile_data_length=tile_data_length,
            output_file=output_file,
            max_required_zoom_offset=max_required_zoom_offset,
            pmtiles_zoom_by_local=pmtiles_zoom_by_local,
        )
