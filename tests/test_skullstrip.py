import json
from pathlib import Path

from analysis.launcher import container_command
from analysis.skullstrip import is_done, log_tail, mounts, placeholders

RUN = {"tool": "fsl-bet", "stem": "sub-01", "subject": "01",
       "t1w": "bids/sub-01/anat/sub-01_T1w.nii.gz", "work_dir": "out/work/fsl-bet/sub-01"}
TOOL = {"name": "fsl-bet", "command": "bet {input} {output_prefix} -m -R",
        "mask_output": "{output_prefix}_mask.nii.gz", "requires": []}
ANTS = {"name": "ants", "requires": ["template.nii.gz"],
        "command": "antsBrainExtraction.sh -a {input} -e {requirements}/template.nii.gz"}


def test_placeholders_match_between_container_and_host():
    inside = placeholders(RUN, 4, {}, TOOL, "container")
    outside = placeholders(RUN, 4, {}, TOOL, "host")
    assert TOOL["mask_output"].format(**inside) == "/output/out_mask.nii.gz"
    assert TOOL["mask_output"].format(**outside) == "out/work/fsl-bet/sub-01/out_mask.nii.gz"
    assert inside["input"] == "/input/sub-01_T1w.nii.gz"


def test_mounts_share_input_read_only_and_skip_missing_tool_dir():
    shared = [(str(host), inside, read_only) for host, inside, read_only in mounts(RUN, TOOL, {})]
    assert shared == [("bids/sub-01/anat", "/input", True),
                      ("out/work/fsl-bet/sub-01", "/output", False)]


def test_both_engines_get_the_same_mounts_and_command(tmp_path):
    shared = [(tmp_path, "/input", True)]
    docker = container_command("docker", "img:1", shared, ["bet", "x"])
    apptainer = container_command("apptainer", "img.sif", shared, ["bet", "x"])
    assert docker[-3:] == ["img:1", "bet", "x"]
    assert apptainer[:3] == ["apptainer", "exec", "--compat"]
    assert f"{tmp_path.resolve()}:/input:ro" in docker
    assert f"{tmp_path.resolve()}:/input:ro" in apptainer


def test_failed_run_counts_as_done_unless_retrying(tmp_path):
    record = tmp_path / "sub-01.json"
    run = {"record": str(record)}
    assert not is_done(run, retry_failed=False)
    record.write_text(json.dumps({"status": "failed"}))
    assert is_done(run, retry_failed=False)
    assert not is_done(run, retry_failed=True)
    record.write_text(json.dumps({"status": "ok"}))
    assert is_done(run, retry_failed=True)


def test_log_tail_prefers_errors_and_skips_the_command_line(tmp_path):
    run = {"log": str(tmp_path / "run.log"), "err": str(tmp_path / "run.err")}
    (tmp_path / "run.log").write_text("# docker run ... the command\nline 1\n")
    (tmp_path / "run.err").write_text("")
    assert log_tail(run) == "line 1"
    (tmp_path / "run.err").write_text("warning\n\nerror: boom\n")
    assert log_tail(run) == "warning | error: boom"


def test_failure_status():
    from analysis.skullstrip import failure_status
    assert failure_status(None, timed_out=True) == "timeout"
    assert failure_status(137, timed_out=False) == "oom"
    assert failure_status(1, timed_out=False) == "failed"


def test_requirements_are_mounted_read_only_per_tool():
    shared = mounts(RUN, ANTS, {"requirements_dir": "/data/requirements"})
    assert (Path("/data/requirements/ants"), "/requirements", True) in shared
    inside = placeholders(RUN, 8, {"requirements_dir": "/data/requirements"}, ANTS, "container")
    assert ANTS["command"].format(**inside).endswith("-e /requirements/template.nii.gz")


def test_threads_reach_the_container_environment(tmp_path):
    for engine in ("docker", "apptainer"):
        command = container_command(engine, "img", [], ["tool"], threads=6)
        assert "ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS=6" in command
        assert "OMP_NUM_THREADS=6" in command


def test_a_run_leaves_only_logs_mask_and_record(tmp_path, monkeypatch):
    """The scratch folder is deleted; the .log ends with the status, the .err with the reason."""
    import analysis.skullstrip as skullstrip

    def fake_container(engine, image, mounts, command, log_file, err_file, **options):
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        Path(log_file).write_text("# fake command\n")
        Path(err_file).write_text("tool: bad input\n")
        return 1

    monkeypatch.setattr(skullstrip, "prepare_image", lambda *arguments: "image")
    monkeypatch.setattr(skullstrip, "run_container", fake_container)
    run = {"tool": "fsl-bet", "stem": "sub-01", "subject": "01", "t1w": "t1w.nii.gz",
           "mask": str(tmp_path / "state" / "masks" / "m.nii.gz"),
           "record": str(tmp_path / "state" / "runs" / "fsl-bet" / "sub-01.json"),
           "log": str(tmp_path / "logs" / "fsl-bet" / "sub-01.log"),
           "err": str(tmp_path / "logs" / "fsl-bet" / "sub-01.err"),
           "work_dir": str(tmp_path / "state" / "work" / "fsl-bet" / "sub-01")}
    plan = {"engine": "docker", "containers_dir": "c", "requirements_dir": None}
    record = skullstrip.run_one(run, {**TOOL, "image": "i"}, plan)

    assert record["status"] == "failed" and "tool: bad input" in record["error"]
    assert not Path(run["work_dir"]).exists()
    assert (tmp_path / "logs" / "fsl-bet" / "sub-01.log").read_text().endswith(
        "# skullstrip-bench: failed in 0 s\n")
    assert "skullstrip-bench: run failed: exit code 1" in Path(run["err"]).read_text()


def test_synthseg_mask_leaves_out_the_csf_around_the_brain(tmp_path):
    import nibabel as nib
    import numpy as np

    from analysis.postprocess import synthseg_brain_mask

    labels = np.zeros((4, 4, 4), dtype=np.int32)
    labels[1, 1, 1], labels[2, 2, 2], labels[3, 3, 3] = 2, 24, 17   # white matter, CSF, other
    nib.save(nib.Nifti1Image(labels, np.eye(4)), tmp_path / "seg.nii.gz")
    t1w = nib.Nifti1Image(np.ones((4, 4, 4), dtype=np.int16), np.eye(4))
    nib.save(t1w, tmp_path / "t1w.nii.gz")
    synthseg_brain_mask(tmp_path / "seg.nii.gz", tmp_path / "t1w.nii.gz", tmp_path / "mask.nii.gz")
    mask = np.asanyarray(nib.load(tmp_path / "mask.nii.gz").dataobj)
    assert mask[1, 1, 1] == 1 and mask[3, 3, 3] == 1
    assert mask[2, 2, 2] == 0 and mask.sum() == 2
