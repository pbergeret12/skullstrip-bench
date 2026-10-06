"""
`run-metrics`: one row per run, with numbers that guide the eye — not a verdict.

There is no ground truth, so each mask is compared with the consensus of all
tools that succeeded on the same T1w (majority vote, voxel by voxel).
"""
import json
from pathlib import Path

import nibabel as nib
import numpy as np
import pandas as pd

COLUMNS = ["subject", "stem", "tool", "status", "volume_ml", "dice_consensus",
           "n_tools_consensus", "duration_s", "error"]


def load_records(runs_dir):
    """Every run record written by `run-skullstrip` (`runs/<tool>/<stem>.json`)."""
    return [json.loads(path.read_text()) for path in sorted(Path(runs_dir).glob("*/*.json"))]


def compute_metrics(runs_dir):
    """Read every run record under `runs_dir`, return the metrics table."""
    records = load_records(runs_dir)
    rows = []
    for stem in sorted({record["stem"] for record in records}):
        rows += metrics_for_one_t1w([record for record in records if record["stem"] == stem])
    return pd.DataFrame(rows, columns=COLUMNS)


def metrics_for_one_t1w(records):
    """Rows for every tool run on the same T1w."""
    masks = {record["tool"]: load_mask(record["mask"])
             for record in records if record["status"] == "ok"}
    consensus = majority_vote(list(masks.values())) if len(masks) >= 2 else None

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
            "n_tools_consensus": len(masks),
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
