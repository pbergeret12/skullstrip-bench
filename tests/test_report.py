import json

import nibabel as nib
import numpy as np
import pandas as pd

from analysis.metrics import update_metrics
from analysis.report import cell_html, update_report


def ok_row(volume_ml):
    return pd.Series({"subject": "01", "status": "ok", "volume_ml": volume_ml,
                      "dice_consensus": np.nan, "duration_s": 3.0, "error": np.nan})


def test_failed_cell_shows_escaped_error(tmp_path):
    row = pd.Series({"subject": "01", "status": "oom", "volume_ml": np.nan,
                     "dice_consensus": np.nan, "duration_s": 3.0, "error": "<killed>"})
    cell = cell_html("sub-01", "ants", row, (tmp_path / "a.jpg", tmp_path / "b.jpg"), (1100, 1600))
    assert "Failed: out of memory" in cell
    assert "&lt;killed&gt;" in cell and "<killed>" not in cell
    assert 'data-rating="bad"' in cell  # a failed run can still be rated
    assert ">Good<" in cell and ">Uncertain<" in cell


def test_implausible_volume_is_highlighted(tmp_path):
    figure = tmp_path / "figure.jpg"
    figure.write_bytes(b"jpg")
    figure = (figure, figure)
    assert "implausible" in cell_html("sub-01", "a", ok_row(1800), figure, (1100, 1600))
    assert "implausible" not in cell_html("sub-01", "a", ok_row(1400), figure, (1100, 1600))
    assert "Dice n/a" in cell_html("sub-01", "a", ok_row(1400), figure, (1100, 1600))


def write_subject(tmp_path, runs_dir, subject, statuses):
    """One fake T1w and mask for `subject`, and a run record per tool."""
    data = np.zeros((40, 40, 40))
    data[10:30, 10:30, 10:30] = 100
    t1w, mask = tmp_path / f"sub-{subject}_T1w.nii.gz", tmp_path / f"sub-{subject}_mask.nii.gz"
    nib.save(nib.Nifti1Image(data, np.eye(4)), t1w)
    nib.save(nib.Nifti1Image((data > 0).astype(np.uint8), np.eye(4)), mask)
    for tool, status in statuses.items():
        (runs_dir / tool).mkdir(parents=True, exist_ok=True)
        (runs_dir / tool / f"sub-{subject}.json").write_text(json.dumps({
            "tool": tool, "stem": f"sub-{subject}", "subject": subject, "status": status,
            "duration_s": 2.0, "error": None if status == "ok" else "boom",
            "t1w": str(t1w), "mask": str(mask) if status == "ok" else None}))


def update(output_dir, plan, subject):
    """Update one subject; return the entry page and the subject's report page."""
    state = output_dir / ".skullstrip-bench"
    update_metrics(state / "runs", state / "metrics_parts", output_dir / "metrics.csv",
                   [subject], tools=list(plan["tools"]))
    update_report(plan, [subject], (1100, 1600))
    return ((output_dir / "report.html").read_text(),
            (output_dir / "pages" / "page_001.html").read_text())


def test_report_grows_as_participants_finish(tmp_path):
    runs_dir = tmp_path / ".skullstrip-bench" / "runs"
    plan = {"output_dir": str(tmp_path), "subjects": ["sub-01", "sub-02"],
            "tools": {"bad": {}, "good": {}}, "participants_per_page": 20}
    write_subject(tmp_path, runs_dir, "01", {"good": "ok", "bad": "failed"})
    index, page = update(tmp_path, plan, "01")
    assert "1 / 2 participants processed" in index
    assert "1 / 2 participants of this page processed" in page
    assert page.count('class="cell"') == 2
    assert "boom" in page and 'data-full="data:image/jpeg;base64,' in page
    assert (tmp_path / "figures" / "good" / "sub-01_full.jpg").is_file()

    write_subject(tmp_path, runs_dir, "02", {"good": "ok", "bad": "ok"})
    index, page = update(tmp_path, plan, "02")
    assert "2 / 2 participants processed" in index
    assert page.count('class="cell"') == 4
    metrics = pd.read_csv(tmp_path / "metrics.csv")
    assert sorted(metrics["subject"].astype(str).str.zfill(2).unique()) == ["01", "02"]
    assert metrics.set_index("stem").loc["sub-02", "dice_consensus"].tolist() == [1.0, 1.0]


def test_pages_split_participants_and_can_be_resplit(tmp_path):
    from analysis.report_pages import page_of, rebuild_index, subject_pages

    runs_dir = tmp_path / ".skullstrip-bench" / "runs"
    subjects = ["01", "02", "03"]
    plan = {"output_dir": str(tmp_path), "subjects": [f"sub-{s}" for s in subjects],
            "tools": {"good": {}}, "participants_per_page": 2}
    for subject in subjects:
        write_subject(tmp_path, runs_dir, subject, {"good": "ok"})
        update(tmp_path, plan, subject)

    assert [len(page) for page in subject_pages(plan)] == [2, 1]
    assert page_of(plan, "03") == 2
    pages_dir = tmp_path / "pages"
    assert sorted(path.name for path in pages_dir.iterdir()) == ["page_001.html", "page_002.html"]
    assert (pages_dir / "page_002.html").read_text().count('class="cell"') == 1
    index = (tmp_path / "report.html").read_text()
    assert 'href="pages/page_002.html"' in index and "3 / 3 participants processed" in index

    # Re-split with one page for everyone: nothing recomputed, stale page removed.
    plan["participants_per_page"] = 10
    update_report(plan, ["01", "02", "03"], (1100, 1600))
    assert sorted(path.name for path in pages_dir.iterdir()) == ["page_001.html"]
    assert (pages_dir / "page_001.html").read_text().count('class="cell"') == 3
    assert rebuild_index(plan, subject_pages(plan)) == 3
