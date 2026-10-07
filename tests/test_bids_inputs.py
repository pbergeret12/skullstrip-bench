import nibabel as nib
import numpy as np
import pytest

from analysis.bids_inputs import (derivative_mask_path, find_t1w, list_subjects, parse,
                                  split_ext)


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


def test_check_mask_rejects_missing_non_binary_and_off_grid(tmp_path):
    from analysis.image_checks import check_mask

    write_image(tmp_path / "t1w.nii.gz")
    mask = np.zeros((64, 64, 64), dtype=np.uint8)
    mask[20:40, 20:40, 20:40] = 1
    nib.save(nib.Nifti1Image(mask, np.eye(4)), tmp_path / "good.nii.gz")
    nib.save(nib.Nifti1Image(mask * 2, np.eye(4)), tmp_path / "labels.nii.gz")
    nib.save(nib.Nifti1Image(mask[:32], np.eye(4)), tmp_path / "small.nii.gz")
    t1w = tmp_path / "t1w.nii.gz"
    assert check_mask(tmp_path / "good.nii.gz", t1w) is None
    assert "no mask" in check_mask(tmp_path / "absent.nii.gz", t1w)
    assert "not binary" in check_mask(tmp_path / "labels.nii.gz", t1w)
    assert "grid" in check_mask(tmp_path / "small.nii.gz", t1w)
