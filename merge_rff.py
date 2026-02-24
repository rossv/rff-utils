#!/usr/bin/env python3
"""
merge_rff.py

Merge multiple SWMM5-RAIN .rff binary rainfall files in a folder into one .rff.

Key features:
- User can point to a folder; script finds all .rff files in it.
- Files are sorted by a quarter-aware heuristic (Q1..Q4) if present in filename,
  otherwise sorted by filename.
- Later files in the sorted list overwrite earlier ones on duplicate timestamps.

Assumptions:
- File starts with ASCII magic: b"SWMM5-RAIN"
- Next 4 bytes: little-endian uint32 gauge_count
- Then gauge_count blocks of 1037 bytes each
  - First 16 bytes: gauge ID (null-padded ASCII)
  - Last 16 bytes: 4 x uint32 (unk0, interval_seconds, start_offset, end_offset)
- Gauge data records are 12 bytes each:
  - float64 time (Excel day serial, origin 1899-12-30)
  - float32 value (rainfall)
"""

from __future__ import annotations

import argparse
import os
import re
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple, Dict, Optional, Callable


MAGIC = b"SWMM5-RAIN"
GAUGE_BLOCK_SIZE = 1037
GAUGE_ID_SIZE = 16
DIR_TAIL_SIZE = 16  # 4 uint32
RECORD_SIZE = 12    # float64 + float32


@dataclass
class GaugeDirEntry:
    gauge_id: str
    raw_block: bytes  # original 1037 bytes (used as template)
    unk0: int
    interval_seconds: int
    start_offset: int
    end_offset: int


@dataclass
class RFFFile:
    path: str
    gauge_count: int
    directory: List[GaugeDirEntry]
    header_size: int  # offset where gauge data begins (after directory)


def _read_exact(f, n: int) -> bytes:
    data = f.read(n)
    if len(data) != n:
        raise EOFError(f"Expected {n} bytes, got {len(data)}")
    return data


def read_rff_header_and_directory(path: str) -> RFFFile:
    with open(path, "rb") as f:
        magic = _read_exact(f, len(MAGIC))
        if magic != MAGIC:
            raise ValueError(f"{path}: Bad magic {magic!r}, expected {MAGIC!r}")

        gauge_count = struct.unpack("<I", _read_exact(f, 4))[0]
        directory: List[GaugeDirEntry] = []

        for _ in range(gauge_count):
            block = _read_exact(f, GAUGE_BLOCK_SIZE)
            gid_raw = block[:GAUGE_ID_SIZE]
            gid = gid_raw.split(b"\x00", 1)[0].decode("ascii", errors="replace")

            unk0, interval_seconds, start_offset, end_offset = struct.unpack(
                "<IIII", block[-DIR_TAIL_SIZE:]
            )

            directory.append(
                GaugeDirEntry(
                    gauge_id=gid,
                    raw_block=block,
                    unk0=unk0,
                    interval_seconds=interval_seconds,
                    start_offset=start_offset,
                    end_offset=end_offset,
                )
            )

        header_size = len(MAGIC) + 4 + gauge_count * GAUGE_BLOCK_SIZE
        return RFFFile(path=path, gauge_count=gauge_count, directory=directory, header_size=header_size)


def validate_compatible(files: List[RFFFile]) -> None:
    if not files:
        raise ValueError("No files provided")

    base = files[0]
    for other in files[1:]:
        if other.gauge_count != base.gauge_count:
            raise ValueError(
                f"Gauge count mismatch: {base.path} has {base.gauge_count}, "
                f"{other.path} has {other.gauge_count}"
            )

        for i, (a, b) in enumerate(zip(base.directory, other.directory)):
            if a.gauge_id != b.gauge_id:
                raise ValueError(
                    f"Gauge ID/order mismatch at index {i}: "
                    f"{base.path}={a.gauge_id!r}, {other.path}={b.gauge_id!r}"
                )

        for i, (a, b) in enumerate(zip(base.directory, other.directory)):
            if a.interval_seconds != b.interval_seconds:
                raise ValueError(
                    f"Interval mismatch for gauge {a.gauge_id!r} at index {i}: "
                    f"{base.path}={a.interval_seconds}, {other.path}={b.interval_seconds}"
                )


def read_gauge_records(path: str, entry: GaugeDirEntry) -> List[Tuple[float, float]]:
    nbytes = entry.end_offset - entry.start_offset
    if nbytes < 0:
        raise ValueError(f"{path}: Negative gauge data length for {entry.gauge_id}")
    if nbytes == 0:
        return []
    if nbytes % RECORD_SIZE != 0:
        raise ValueError(
            f"{path}: Gauge {entry.gauge_id} data length {nbytes} not divisible by {RECORD_SIZE}"
        )

    with open(path, "rb") as f:
        f.seek(entry.start_offset)
        blob = _read_exact(f, nbytes)

    recs: List[Tuple[float, float]] = []
    for t, v in struct.iter_unpack("<df", blob):
        recs.append((t, float(v)))
    return recs


def merge_records_with_precedence(list_of_record_lists: List[List[Tuple[float, float]]]) -> List[Tuple[float, float]]:
    merged: Dict[float, float] = {}
    for recs in list_of_record_lists:
        for t, v in recs:
            merged[t] = v  # later overwrites earlier
    out = sorted(merged.items(), key=lambda x: x[0])
    return [(t, v) for t, v in out]


def pack_records(records: List[Tuple[float, float]]) -> bytes:
    if not records:
        return b""
    buf = bytearray(len(records) * RECORD_SIZE)
    offset = 0
    for t, v in records:
        struct.pack_into("<df", buf, offset, t, float(v))
        offset += RECORD_SIZE
    return bytes(buf)


def patch_directory_block(block: bytes, start_offset: int, end_offset: int) -> bytes:
    if len(block) != GAUGE_BLOCK_SIZE:
        raise ValueError("Invalid gauge directory block size")
    unk0, interval_seconds, _, _ = struct.unpack("<IIII", block[-DIR_TAIL_SIZE:])
    tail = struct.pack("<IIII", unk0, interval_seconds, start_offset, end_offset)
    return block[:-DIR_TAIL_SIZE] + tail


_QUARTER_RE = re.compile(r"(?:^|[^A-Z0-9])Q([1-4])(?:[^A-Z0-9]|$)", re.IGNORECASE)
_YEAR_RE = re.compile(r"(19\d{2}|20\d{2})")


def sort_key_for_rff_name(name: str) -> Tuple[int, int, str]:
    """
    Returns (year, quarter, name) where missing year/quarter become large defaults.
    This makes Q1..Q4 sort correctly within a year if patterns are present.
    """
    upper = name.upper()

    year = 9999
    m_year = _YEAR_RE.search(upper)
    if m_year:
        year = int(m_year.group(1))

    quarter = 99
    m_q = _QUARTER_RE.search(upper)
    if m_q:
        quarter = int(m_q.group(1))

    return (year, quarter, name)


def discover_inputs(folder: Path, recursive: bool) -> List[Path]:
    if recursive:
        files = list(folder.rglob("*.rff"))
    else:
        files = list(folder.glob("*.rff"))
    files = [p for p in files if p.is_file()]
    files.sort(key=lambda p: sort_key_for_rff_name(p.name))
    return files


def merge_rff(input_paths: List[str], output_path: str, progress_every: int = 25, progress_callback: Optional[Callable[[int, int, str], None]] = None) -> None:
    print("Reading headers/directories...")
    rffs = [read_rff_header_and_directory(p) for p in input_paths]
    validate_compatible(rffs)

    gauge_count = rffs[0].gauge_count
    print(f"Files: {len(rffs)}")
    for idx, r in enumerate(rffs, start=1):
        size_mb = os.path.getsize(r.path) / (1024 * 1024)
        print(f"  {idx}. {r.path}  ({size_mb:.1f} MB)")
    print(f"Gauge count: {gauge_count}")
    print(f"Interval (seconds): {rffs[0].directory[0].interval_seconds} (from first gauge)")
    print("Dedup rule: later files in this list overwrite earlier ones on same timestamp.")

    print("Preparing output file (writing header + placeholder directory)...")
    base_dir = rffs[0].directory

    with open(output_path, "wb") as out:
        out.write(MAGIC)
        out.write(struct.pack("<I", gauge_count))

        for e in base_dir:
            out.write(e.raw_block)

        print("Merging gauge data and writing output...")
        current_offset = len(MAGIC) + 4 + gauge_count * GAUGE_BLOCK_SIZE
        new_blocks: List[bytes] = [b""] * gauge_count

        for i in range(gauge_count):
            gid = base_dir[i].gauge_id

            if progress_callback:
                progress_callback(i + 1, gauge_count, gid)
            elif i == 0 or (i + 1) % progress_every == 0 or (i + 1) == gauge_count:
                print(f"  Gauge {i+1}/{gauge_count}: {gid}")

            per_file_records: List[List[Tuple[float, float]]] = []
            for rff in rffs:
                entry = rff.directory[i]
                recs = read_gauge_records(rff.path, entry)
                per_file_records.append(recs)

            merged = merge_records_with_precedence(per_file_records)
            blob = pack_records(merged)

            start = current_offset
            out.write(blob)
            current_offset += len(blob)
            end = current_offset

            new_blocks[i] = patch_directory_block(base_dir[i].raw_block, start, end)

        print("Patching directory offsets...")
        out.seek(len(MAGIC) + 4)
        for b in new_blocks:
            out.write(b)

    out_size_mb = os.path.getsize(output_path) / (1024 * 1024)
    print(f"Done. Wrote: {output_path} ({out_size_mb:.1f} MB)")


def parse_args(argv: List[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Merge all SWMM5-RAIN .rff files in a folder into one .rff. Later files overwrite earlier on duplicate timestamps."
    )
    p.add_argument(
        "--folder",
        required=True,
        help="Folder containing .rff files to merge",
    )
    p.add_argument(
        "--recursive",
        action="store_true",
        help="Search for .rff files recursively under the folder",
    )
    p.add_argument(
        "-o",
        "--output",
        required=True,
        help="Output .rff path",
    )
    p.add_argument(
        "--progress-every",
        type=int,
        default=25,
        help="Print progress every N gauges (default: 25)",
    )
    return p.parse_args(argv)


def main(argv: List[str]) -> int:
    args = parse_args(argv)
    folder = Path(args.folder).expanduser().resolve()

    if not folder.exists() or not folder.is_dir():
        print(f"ERROR: Folder not found or not a directory: {folder}", file=sys.stderr)
        return 2

    inputs = discover_inputs(folder, recursive=args.recursive)
    if not inputs:
        print(f"ERROR: No .rff files found in: {folder}", file=sys.stderr)
        return 2

    print("Discovered .rff files (merge order):")
    for i, p in enumerate(inputs, start=1):
        print(f"  {i}. {p.name}")

    output = Path(args.output).expanduser().resolve()
    if not output.parent.exists():
        print(f"ERROR: Output directory does not exist: {output.parent}", file=sys.stderr)
        return 2

    merge_rff([str(p) for p in inputs], str(output), progress_every=args.progress_every)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))