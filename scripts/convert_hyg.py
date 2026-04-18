#!/usr/bin/env python3
# scripts/convert_hyg.py
# One-time conversion: HYG catalog CSV → atlas binary star catalog (stars.npy)
#
# Usage:
#   python scripts/convert_hyg.py <path/to/hygdata_v41.csv> [out_path] [mag_limit]
#
# Defaults:
#   out_path  = src/atlas/data/stars.npy
#   mag_limit = 99.0  (keep everything; dome filters at render time)

# Standard Modules
import csv
import sys
from pathlib import Path

# External Modules
import numpy as np


DTYPE = np.dtype([
    ("ra",    np.float32),   # RA in degrees (converted from hours)
    ("dec",   np.float32),   # Dec in degrees
    ("mag",   np.float32),   # Apparent magnitude
    ("ci",    np.float32),   # B-V color index (star color)
    ("name",  "S20"),        # Proper name, ASCII, up to 20 chars (empty if unnamed)
    ("spect", "S8"),         # Spectral type, ASCII, up to 8 chars
])


# Convert HYG CSV to numpy binary
def convert(csv_path: str, out_path: str, mag_limit: float = 99.0) -> None:
    records = []

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                mag = float(row["mag"]) if row["mag"].strip() else 99.0
                if mag > mag_limit:
                    continue

                ra_deg = float(row["ra"]) * 15.0
                dec    = float(row["dec"])
                ci     = float(row["ci"])    if row["ci"].strip()    else 0.6
                name   = row["proper"].strip()[:20].encode("ascii", errors="replace")
                spect  = row["spect"].strip()[:8].encode("ascii",  errors="replace")

                records.append((ra_deg, dec, mag, ci, name, spect))

            except (ValueError, KeyError):
                continue

    arr = np.array(records, dtype=DTYPE)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    np.save(out_path, arr)

    named   = np.count_nonzero(arr["name"])
    print(f"Saved {len(arr):,} stars ({named:,} named) → {out_path}")
    print(f"Magnitude range: {arr['mag'].min():.2f} to {arr['mag'].max():.2f}")
    print(f"File size: {Path(out_path).stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    csv_path  = sys.argv[1] if len(sys.argv) > 1 else "hygdata_v41.csv"
    out_path  = sys.argv[2] if len(sys.argv) > 2 else "src/atlas/data/stars.npy"
    mag_limit = float(sys.argv[3]) if len(sys.argv) > 3 else 99.0
    convert(csv_path, out_path, mag_limit)
