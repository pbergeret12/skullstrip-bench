"""
Incremental outputs: each participant writes its own part, then the shared
file (metrics.csv, report.html) is rebuilt from every part present.

Many cluster jobs may finish at the same time, and someone may be reading the
report while it changes, so:
- a file is always written to a temporary name, then renamed: a reader never
  sees half a file;
- after writing, the parts are listed again; if some appeared or changed
  meanwhile, the file is rebuilt, so the last job to finish leaves a complete file. The final
  report job rebuilds everything anyway.
"""
import os
from pathlib import Path

MAX_REBUILDS = 5


def write_atomically(path, text):
    """Write `text` to `path` through a temporary file and a rename."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(text)
    temporary.replace(path)


def list_parts(parts_dir, suffix):
    """The parts written so far, sorted by name (one per participant)."""
    return sorted(Path(parts_dir).glob(f"sub-*{suffix}"))


def rebuild_from_parts(parts_dir, suffix, output_file, build):
    """
    Write `build(parts)` to `output_file`, until no new part has appeared
    while it was being written. Returns the parts used.
    """
    parts = list_parts(parts_dir, suffix)
    for _ in range(MAX_REBUILDS):
        seen = snapshot(parts)
        write_atomically(output_file, build(parts))
        parts = list_parts(parts_dir, suffix)
        if snapshot(parts) == seen:
            break
    return parts


def snapshot(parts):
    """Which parts exist and when each was last written."""
    return [(part, part.stat().st_mtime_ns) for part in parts if part.exists()]
