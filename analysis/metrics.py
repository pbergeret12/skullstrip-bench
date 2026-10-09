"""
`run-metrics`: one row per run, with numbers that guide the eye — not a verdict.

There is no ground truth, so each mask is compared with the consensus of all
tools that succeeded on the same T1w (majority vote, voxel by voxel). Masks
refined by recon-all (`synthseg+reconall`) get a Dice too, but do not vote:
they would count their base tool twice. Since
the consensus only involves one T1w, a participant's metrics can be computed
as soon as that participant is done: each one gets its own part (internal
state), and `report/metrics.csv` is rebuilt from the parts.
"""
import io
import json
from pathlib import Path

import nibabel as nib
import numpy as np
import pandas as pd

from analysis.assemble import rebuild_from_parts, write_atomically

COLUMNS = ["subject", "stem", "tool", "status", "volume_ml", "dice_consensus",
           "n_tools_consensus", "duration_s", "error"]


def load_records(runs_dir, subject=None, tools=None):
    """
    The run records written by `run-skullstrip` (`runs/<tool>/<stem>.json`),
    optionally for one subject and some tools only.
    """
    patterns = [f"sub-{subject}.json", f"sub-{subject}_*.json"] if subject else ["*.json"]
    paths = sorted({path for pattern in patterns for path in Path(runs_dir).glob(f"*/{pattern}")})
    records = [json.loads(path.read_text()) for path in paths]
    return [record for record in records if not tools or record["tool"] in tools]


def update_metrics(runs_dir, parts_dir, metrics_csv, subjects, tools=None):
    """Rewrite the metrics part of each subject, then rebuild `metrics.csv`."""
    for subject in subjects:
        table = metrics_table(load_records(runs_dir, subject, tools))
        write_atomically(Path(parts_dir) / f"sub-{subject}.csv", table.to_csv(index=False))
    return rebuild_from_parts(parts_dir, ".csv", metrics_csv, concatenate_csv)


def concatenate_csv(parts):
    """One CSV text holding the rows of every part."""
    tables = [pd.read_csv(part) for part in parts]
    table = pd.concat(tables) if tables else pd.DataFrame(columns=COLUMNS)
    buffer = io.StringIO()
    table.to_csv(buffer, index=False)
    return buffer.getvalue()


def metrics_table(records):
    """The metrics of these records, one row per run, grouped by T1w."""
    rows = []
    for stem in sorted({record["stem"] for record in records}):
        rows += metrics_for_one_t1w([record for record in records if record["stem"] == stem])
    return pd.DataFrame(rows, columns=COLUMNS)


def compute_metrics(runs_dir, tools=None):
    """The metrics table of every run under `runs_dir`."""
    return metrics_table(load_records(runs_dir, tools=tools))


def metrics_for_one_t1w(records):
    """Rows for every tool run on the same T1w."""
    masks = {record["tool"]: load_mask(record["mask"])
             for record in records if record["status"] == "ok"}
    voters = [masks[record["tool"]] for record in records
              if record["tool"] in masks and not record.get("refines")]
    consensus = majority_vote(voters) if len(voters) >= 2 else None

    rows = []
    for record in records:
        mask, voxel_ml = masks.get(record["tool"], (None, None))
        rows.append({
            "subject": record["subject"],
            "stem": record["stem"],
            "tool": record["tool"],
            "status": record["status"],
            "volume_ml": round(mask.sum() * voxel_ml, 1) if mask is not None else None,
            "dice_consensus": (round(dice(mask, consensus), 4)
                               if mask is not None and consensus is not None else None),
            "n_tools_consensus": len(voters),
            "duration_s": record["duration_s"],
            "error": record["error"],
        })
    return rows


def load_mask(path):
    """A mask as a boolean array, and the volume of one voxel in mL."""
    image = nib.load(path)
    voxel_ml = float(np.prod(image.header.get_zooms()[:3])) / 1000
    return np.asanyarray(image.dataobj) > 0, voxel_ml


def majority_vote(masks_and_voxel_sizes):
    """Voxels inside more than half of the masks."""
    masks = [mask for mask, _ in masks_and_voxel_sizes]
    return np.sum(masks, axis=0) > len(masks) / 2


def dice(mask_a, mask_b):
    """Overlap between two boolean masks: 1 identical, 0 disjoint."""
    total = mask_a.sum() + mask_b.sum()
    return 2 * np.logical_and(mask_a, mask_b).sum() / total if total else np.nan
