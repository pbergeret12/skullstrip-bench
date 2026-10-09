import json

import nibabel as nib
import numpy as np
import pytest

from analysis.metrics import compute_metrics, dice, majority_vote


def test_dice_identical_disjoint_and_half():
    a = np.array([1, 1, 0, 0], dtype=bool)
    assert dice(a, a) == 1
    assert dice(a, ~a) == 0
    assert dice(a, np.array([1, 0, 0, 0], dtype=bool)) == pytest.approx(2 / 3)


def test_majority_vote_needs_more_than_half():
    masks = [(np.array([1, 1, 0], dtype=bool), 1), (np.array([1, 0, 0], dtype=bool), 1),
             (np.array([1, 1, 1], dtype=bool), 1)]
    assert majority_vote(masks).tolist() == [True, True, False]


def write_run(runs_dir, tool, status, mask_data=None, refines=None):
    mask_path = None
    if mask_data is not None:
        mask_path = runs_dir.parent / f"{tool}.nii.gz"
        affine = np.diag([2, 2, 2, 1])  # 8 mm³ voxels
        nib.save(nib.Nifti1Image(mask_data.astype(np.uint8), affine), mask_path)
    (runs_dir / tool).mkdir(parents=True)
    (runs_dir / tool / "sub-01.json").write_text(json.dumps({
        "tool": tool, "stem": "sub-01", "subject": "01", "status": status,
        "duration_s": 1.0, "error": None if status == "ok" else "boom",
        "mask": str(mask_path) if mask_path else None, "refines": refines}))


def test_compute_metrics_volume_dice_and_failed_run(tmp_path):
    runs_dir = tmp_path / "runs"
    full = np.ones((10, 10, 10))
    write_run(runs_dir, "a", "ok", full)
    write_run(runs_dir, "b", "ok", full)
    write_run(runs_dir, "c", "failed")
    table = compute_metrics(runs_dir).set_index("tool")
    assert table.loc["a", "volume_ml"] == 8.0  # 1000 voxels × 8 mm³
    assert table.loc["a", "dice_consensus"] == 1.0
    assert table.loc["a", "n_tools_consensus"] == 2
    assert np.isnan(table.loc["c", "volume_ml"])
    assert table.loc["c", "error"] == "boom"


def test_refined_masks_get_a_dice_but_do_not_vote(tmp_path):
    runs_dir = tmp_path / "runs"
    full, empty = np.ones((10, 10, 10)), np.zeros((10, 10, 10))
    write_run(runs_dir, "a", "ok", full)
    write_run(runs_dir, "b", "ok", full)
    # Two refined copies of an empty mask would outvote a and b if they voted.
    write_run(runs_dir, "a+reconall", "ok", empty, refines="a")
    write_run(runs_dir, "b+reconall", "ok", empty, refines="b")
    table = compute_metrics(runs_dir).set_index("tool")
    assert table.loc["a", "dice_consensus"] == 1.0
    assert table.loc["a+reconall", "dice_consensus"] == 0.0
    assert table.loc["a+reconall", "n_tools_consensus"] == 2
