import json

import nibabel as nib
import numpy as np
import yaml

from analysis.check import check_dataset, check_tools
from analysis.slurm import participant_resources, write_slurm_files


def make_bids(root, subjects_with_t1w, subjects_without=()):
    (root / "dataset_description.json").write_text("{}")
    for subject in subjects_with_t1w:
        path = root / f"sub-{subject}" / "anat" / f"sub-{subject}_T1w.nii.gz"
        path.parent.mkdir(parents=True)
        nib.save(nib.Nifti1Image(np.zeros((4, 4, 4), dtype=np.uint8), np.eye(4)), path)
    for subject in subjects_without:
        (root / f"sub-{subject}" / "func").mkdir(parents=True)
    return root


def test_dataset_check_is_shallow_and_filters_subjects(tmp_path):
    bids = make_bids(tmp_path, ["01", "02"], subjects_without=["03"])
    # A corrupt T1w is not opened by the check: it stays in the plan.
    (bids / "sub-02" / "anat" / "sub-02_T1w.nii.gz").write_text("not an image")
    assert [t1w["stem"] for t1w in check_dataset(bids)] == ["sub-01", "sub-02"]
    assert [t1w["stem"] for t1w in check_dataset(bids, subjects=["sub-02"])] == ["sub-02"]
    assert check_dataset(tmp_path / "nowhere") == []


def write_tool(tools_dir, name, container, **extra):
    config = {"name": name, "image": f"{name}:1", "container": container,
              "command": "tool {input} {mask}", **extra}
    (tools_dir / f"{name}.yaml").write_text(yaml.safe_dump(config))


def test_without_tools_every_compatible_image_is_used(tmp_path):
    tools_dir, containers = tmp_path / "tools", tmp_path / "containers"
    tools_dir.mkdir()
    containers.mkdir()
    write_tool(tools_dir, "fast", "fast_1")
    write_tool(tools_dir, "atlas", "atlas_1", requires=["a.nii.gz"])
    write_tool(tools_dir, "absent", "absent_1")
    for image in ("fast_1.sif", "atlas_1.sif", "mystery_2.tar"):
        (containers / image).write_text("")
    paths = {"tools_dir": tools_dir, "containers_dir": containers, "requirements_dir": None}

    usable = check_tools(paths, "apptainer")
    assert sorted(usable) == ["fast"]   # atlas lacks its requirement, absent has no image

    (tmp_path / "req" / "atlas").mkdir(parents=True)
    (tmp_path / "req" / "atlas" / "a.nii.gz").write_text("")
    paths["requirements_dir"] = tmp_path / "req"
    assert sorted(check_tools(paths, "apptainer")) == ["atlas", "fast"]
    assert sorted(check_tools(paths, "apptainer", wanted=["fast", "nope"])) == ["fast"]


def test_cluster_jobs_require_built_sif(tmp_path):
    tools_dir, containers = tmp_path / "tools", tmp_path / "containers"
    tools_dir.mkdir()
    containers.mkdir()
    write_tool(tools_dir, "fast", "fast_1")
    (containers / "fast_1.tar").write_text("")
    paths = {"tools_dir": tools_dir, "containers_dir": containers, "requirements_dir": None}
    assert check_tools(paths, "apptainer") != {}
    assert check_tools(paths, "apptainer", require_sif=True) == {}


def slurm_plan(tmp_path):
    tools = {"fast": {"cpus": 4, "mem_gb": 8, "minutes": 3},
             "slow": {"cpus": 8, "mem_gb": 16, "minutes": 20}}
    stems = [("01", "sub-01_run-1"), ("01", "sub-01_run-2"), ("02", "sub-02")]
    runs = [{"tool": tool, "subject": subject, "stem": stem}
            for subject, stem in stems for tool in tools]
    return {"output_dir": str(tmp_path / "out"), "workdir": str(tmp_path / "work"),
            "tools": tools, "runs": runs, "subjects": ["sub-01", "sub-02"]}


def test_resources_take_largest_tool_and_busiest_participant(tmp_path):
    resources = participant_resources(slurm_plan(tmp_path))
    assert (resources["cpus"], resources["mem_gb"]) == (8, 16)
    assert resources["expected_minutes"] == 46      # 2 T1w × (3 + 20) min
    assert resources["minutes"] == 90               # 46 × 1.5 + 10 = 79 → 90


def test_measured_apptainer_durations_replace_estimates(tmp_path):
    plan = slurm_plan(tmp_path)
    record_dir = tmp_path / "out" / ".skullstrip-bench" / "runs" / "slow"
    record_dir.mkdir(parents=True)
    (record_dir / "sub-02.json").write_text(json.dumps(
        {"status": "ok", "engine": "apptainer", "duration_s": 300}))
    resources = participant_resources(plan)
    assert resources["per_tool"]["slow"] == (5.0, "measured")
    assert resources["per_tool"]["fast"] == (3, "estimated")


def test_one_sbatch_and_jobs_txt_in_the_workdir(tmp_path):
    sbatch_file, _ = write_slurm_files(slurm_plan(tmp_path), tmp_path, "/env/bin/invoke",
                                       "invoke run --scheduler slurm")
    workdir = tmp_path / "work"
    assert sbatch_file == workdir / "skullstrip_bench_sbatch.sh"
    assert sorted(path.name for path in workdir.iterdir()) == [
        "jobs.txt", "logs", "skullstrip_bench_sbatch.sh"]
    assert (workdir / "jobs.txt").read_text() == "sub-01\nsub-02\n"
    sbatch = sbatch_file.read_text()
    assert "#SBATCH --account=def-CHANGEME" in sbatch
    assert "#SBATCH --array=1-2\n" in sbatch
    assert "#SBATCH --time=01:30:00" in sbatch
    assert f"#SBATCH --output={workdir / 'logs'}/slurm_%A_%a.log" in sbatch
    assert f"#SBATCH --error={workdir / 'logs'}/slurm_%A_%a.err" in sbatch
    assert '--threads "$SLURM_CPUS_PER_TASK" --work-root "$SLURM_TMPDIR/work"' in sbatch
    assert 'run-update --output' in sbatch
    assert not (tmp_path / "out").exists()   # nothing about Slurm in the results folder


def test_from_the_tool_container_jobs_rerun_the_same_image(tmp_path, monkeypatch):
    monkeypatch.setenv("SKULLSTRIP_BENCH_IN_CONTAINER", "1")
    monkeypatch.setenv("APPTAINER_CONTAINER", "/images/skullstrip-bench.sif")
    plan = {**slurm_plan(tmp_path), "bids_dir": "/data/bids", "containers_dir": "/data/img"}
    sbatch_file, _ = write_slurm_files(plan, tmp_path, "/env/bin/invoke", "cmd")
    sbatch = sbatch_file.read_text()
    expected = ("apptainer exec --bind /data/bids,/data/img,"
                f"{tmp_path / 'out'},{tmp_path / 'work'},\"$SLURM_TMPDIR\" "
                "/images/skullstrip-bench.sif skullstrip-bench run-skullstrip")
    assert expected in sbatch
    assert "cd " not in sbatch
