import json

import nibabel as nib
import numpy as np
import pytest
import yaml

from analysis.check import run_check
from analysis.postprocess import fmriprep_brain_mask
from analysis.reconall import prepare_input


def save(path, data, affine=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    nib.save(nib.Nifti1Image(data, np.eye(4) if affine is None else affine), path)
    return path


def setup_project(tmp_path, with_license=True):
    """A dataset of one T1w, a fast tool and the reconall refiner, both images present."""
    bids, tools, containers = tmp_path / "bids", tmp_path / "tools", tmp_path / "containers"
    (bids / "dataset_description.json").parent.mkdir(parents=True)
    (bids / "dataset_description.json").write_text("{}")
    save(bids / "sub-01" / "anat" / "sub-01_T1w.nii.gz", np.zeros((4, 4, 4), dtype=np.int16))
    tools.mkdir()
    containers.mkdir()
    for name, extra in (("fast", {}), ("reconall", {"refines_masks": True})):
        config = {"name": name, "image": f"{name}:1", "container": f"{name}_1",
                  "command": "tool {input} {mask}", **extra}
        (tools / f"{name}.yaml").write_text(yaml.safe_dump(config))
        (containers / f"{name}_1.sif").write_text("")
    if with_license:
        (containers / "license.txt").write_text("license")
    return {"bids_dir": bids, "containers_dir": containers, "tools_dir": tools,
            "requirements_dir": None, "output_dir": tmp_path / "out", "workdir": tmp_path}


def test_refiner_is_never_a_tool_of_its_own(tmp_path, monkeypatch):
    monkeypatch.setattr("analysis.check.detect_engine", lambda forced: ("apptainer", None))
    plan = run_check(setup_project(tmp_path))
    assert list(plan["tools"]) == ["fast"]


def test_reconall_adds_a_refining_run_after_its_base(tmp_path, monkeypatch):
    monkeypatch.setattr("analysis.check.detect_engine", lambda forced: ("apptainer", None))
    plan = run_check(setup_project(tmp_path), reconall=["fast"])
    assert [run["tool"] for run in plan["runs"]] == ["fast", "fast+reconall"]
    base, refining = plan["runs"]
    assert refining["refines"] == "fast" and refining["base_mask"] == base["mask"]
    assert plan["tools"]["fast+reconall"]["refines"] == "fast"


def test_reconall_needs_the_license_and_a_base_that_runs(tmp_path, monkeypatch):
    monkeypatch.setattr("analysis.check.detect_engine", lambda forced: ("apptainer", None))
    no_license = run_check(setup_project(tmp_path / "a", with_license=False), reconall=["fast"])
    assert list(no_license["tools"]) == ["fast"]
    unknown_base = run_check(setup_project(tmp_path / "b"), reconall=["slow"])
    assert list(unknown_base["tools"]) == ["fast"]


def test_prepare_input_strips_the_t1w_with_the_base_mask(tmp_path):
    t1w = save(tmp_path / "t1w.nii.gz", np.full((4, 4, 4), 7, dtype=np.int16))
    mask_data = np.zeros((4, 4, 4), dtype=np.uint8)
    mask_data[1:3, 1:3, 1:3] = 1
    mask = save(tmp_path / "mask.nii.gz", mask_data)
    run = {"t1w": str(t1w), "base_mask": str(mask), "refines": "fast"}
    prepare_input(run, tmp_path / "bids")
    stripped = nib.load(tmp_path / "bids" / "sub-01" / "anat" / "sub-01_T1w.nii.gz")
    assert np.asanyarray(stripped.dataobj).sum() == 7 * 8
    assert json.loads((tmp_path / "bids" / "dataset_description.json").read_text())["Name"]

    with pytest.raises(RuntimeError, match="no fast mask"):
        prepare_input({**run, "base_mask": str(tmp_path / "missing.nii.gz")}, tmp_path / "b2")


def test_fmriprep_mask_is_found_and_put_back_on_the_t1w_grid(tmp_path):
    t1w = save(tmp_path / "t1w.nii.gz", np.ones((4, 4, 4), dtype=np.int16))
    anat = tmp_path / "fmriprep" / "sub-01" / "anat"
    data = np.zeros((4, 4, 4), dtype=np.uint8)
    data[0, 0, 0] = 1
    save(anat / "sub-01_desc-brain_mask.nii.gz", data)
    save(anat / "sub-01_space-MNI152NLin2009cAsym_desc-brain_mask.nii.gz", np.ones((4, 4, 4)))
    fmriprep_brain_mask(tmp_path / "fmriprep", t1w, tmp_path / "mask.nii.gz")
    assert np.asanyarray(nib.load(tmp_path / "mask.nii.gz").dataobj).sum() == 1

    with pytest.raises(RuntimeError, match="no anatomical desc-brain_mask"):
        fmriprep_brain_mask(tmp_path / "nothing", t1w, tmp_path / "mask2.nii.gz")
