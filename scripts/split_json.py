"""Split a large JSON array file into N smaller JSON files."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def count_objects(json_file: Path) -> int:
    with json_file.open(encoding="utf-8") as f:
        data = json.load(f)
    return len(data)


def split_json_file(json_file: Path, num_files: int) -> None:
    with json_file.open(encoding="utf-8") as f:
        data = json.load(f)
    n = len(data)
    base = json_file.stem
    parent = json_file.parent
    per = n // num_files
    rem = n % num_files
    idx = 0
    for i in range(num_files):
        chunk = per + (1 if i < rem else 0)
        part = data[idx : idx + chunk]
        idx += chunk
        out = parent / f"{base}_{i + 1}.json"
        with out.open("w", encoding="utf-8") as f:
            json.dump(part, f, indent=4, ensure_ascii=False)
        print(f"Wrote {out} ({len(part)} objects)")


def main() -> None:
    ap = argparse.ArgumentParser(description="Split JSON array into N files")
    ap.add_argument("json_file", type=str)
    ap.add_argument("num_files", type=int)
    args = ap.parse_args()
    p = Path(args.json_file)
    if not p.is_file():
        print(f"Not found: {p}")
        sys.exit(1)
    n = count_objects(p)
    print(f"Objects: {n}")
    split_json_file(p, args.num_files)


if __name__ == "__main__":
    main()
