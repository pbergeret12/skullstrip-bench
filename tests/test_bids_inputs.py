import nibabel as nib
import numpy as np
import pytest

from analysis.bids_inputs import (derivative_mask_path, find_t1w, list_subjects, parse,
                                  split_ext)
from analysis.image_checks import check_t1w


def write_image(path, shape=(64, 64, 64)):
    path.parent.mkdir(parents=True, exist_ok=True)
    nib.save(nib.Nifti1Image(np.zeros(shape, dtype=np.uint8), np.eye(4)), path)


@pytest.fixture
def bids_dir(tmp_path):
    """A fake dataset: sessions, two runs, an acquisition, and a subject without T1w."""
    for name in ("sub-01/anat/sub-01_T1w.nii.gz",
                 "sub-02/ses-pre/anat/sub-02_ses-pre_acq-mprage_run-1_T1w.nii.gz",
                 "sub-02/ses-pre/anat/sub-02_ses-pre_acq-mprage_run-2_T1w.nii.gz",
                 "sub-03/func/sub-03_task-rest_bold.nii.gz"):
        write_image(tmp_path / name)
    return tmp_path


def test_split_ext_keeps_nii_gz_together():
    assert split_ext("a/sub-01_T1w.nii.gz") == ("sub-01_T1w", ".nii.gz")


def test_parse_reads_entities_and_suffix():
    assert parse("sub-01_ses-pre_run-2_T1w.nii.gz") == {
        "sub": "01", "ses": "pre", "run": "2", "suffix": "T1w", "extension": ".nii.gz"}


def test_find_t1w_handles_sessions_and_runs(bids_dir):
    stems = [t1w["stem"] for t1w in find_t1w(bids_dir)]
    assert stems == ["sub-01",
                     "sub-02_ses-pre_acq-mprage_run-1",
                     "sub-02_ses-pre_acq-mprage_run-2"]


def test_subject_without_t1w_is_listed_but_has_no_image(bids_dir):
    assert list_subjects(bids_dir) == ["01", "02", "03"]
    assert all(t1w["entities"]["sub"] != "03" for t1w in find_t1w(bids_dir))


def test_derivative_path_keeps_session_and_entities(bids_dir):
    t1w = find_t1w(bids_dir)[1]
    path = derivative_mask_path("derivatives", "synthstrip", t1w)
    assert str(path) == ("derivatives/synthstrip/sub-02/ses-pre/anat/"
                         "sub-02_ses-pre_acq-mprage_run-1_desc-brain_mask.nii.gz")


def test_check_t1w_accepts_3d_and_rejects_4d(tmp_path):
    write_image(tmp_path / "ok.nii.gz")
    write_image(tmp_path / "bold.nii.gz", shape=(64, 64, 64, 10))
    assert check_t1w(tmp_path / "ok.nii.gz")[0] is None
    assert "4D" in check_t1w(tmp_path / "bold.nii.gz")[0]


def test_check_t1w_reports_unreadable_file(tmp_path):
    broken = tmp_path / "broken.nii.gz"
    broken.write_text("not an image")
    assert "cannot be read" in check_t1w(broken)[0]
