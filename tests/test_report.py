import json

import nibabel as nib
import numpy as np
import pandas as pd

from analysis.metrics import compute_metrics
from analysis.report import build_report, cell_html


def ok_row(volume_ml):
    return pd.Series({"subject": "01", "status": "ok", "volume_ml": volume_ml,
                      "dice_consensus": np.nan, "duration_s": 3.0, "error": np.nan})


def test_failed_cell_shows_escaped_error(tmp_path):
    row = pd.Series({"subject": "01", "status": "oom", "volume_ml": np.nan,
                     "dice_consensus": np.nan, "duration_s": 3.0, "error": "<killed>"})
    cell = cell_html("sub-01", "ants", row, (tmp_path / "a.jpg", tmp_path / "b.jpg"), (1100, 1600))
    assert "Failed: out of memory" in cell
    assert "&lt;killed&gt;" in cell and "<killed>" not in cell
    assert 'data-rating="ok"' in cell  # a failed run can still be rated


def test_implausible_volume_is_highlighted(tmp_path):
    figure = tmp_path / "figure.jpg"
    figure.write_bytes(b"jpg")
    figure = (figure, figure)
    assert "implausible" in cell_html("sub-01", "a", ok_row(1800), figure, (1100, 1600))
    assert "implausible" not in cell_html("sub-01", "a", ok_row(1400), figure, (1100, 1600))
    assert "Dice n/a" in cell_html("sub-01", "a", ok_row(1400), figure, (1100, 1600))


def test_build_report_end_to_end(tmp_path):
    data = np.zeros((40, 40, 40))
    data[10:30, 10:30, 10:30] = 100
    t1w, mask = tmp_path / "t1w.nii.gz", tmp_path / "mask.nii.gz"
    nib.save(nib.Nifti1Image(data, np.eye(4)), t1w)
    nib.save(nib.Nifti1Image((data > 0).astype(np.uint8), np.eye(4)), mask)
    runs_dir = tmp_path / "runs"
    for tool, status in (("good", "ok"), ("bad", "failed")):
        (runs_dir / tool).mkdir(parents=True)
        (runs_dir / tool / "sub-01.json").write_text(json.dumps({
            "tool": tool, "stem": "sub-01", "subject": "01", "status": status,
            "duration_s": 2.0, "error": None if status == "ok" else "boom",
            "t1w": str(t1w), "mask": str(mask) if status == "ok" else None}))
    compute_metrics(runs_dir).to_csv(tmp_path / "metrics.csv", index=False)

    report = tmp_path / "report.html"
    build_report(runs_dir, tmp_path / "metrics.csv", tmp_path / "figures", report, (1100, 1600))

    page = report.read_text()
    assert (tmp_path / "figures" / "good" / "sub-01.jpg").is_file()
    assert (tmp_path / "figures" / "good" / "sub-01_full.jpg").is_file()
    assert page.count('class="cell"') == 2
    assert 'data-full="data:image/jpeg;base64,' in page and "boom" in page
