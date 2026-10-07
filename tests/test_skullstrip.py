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
    inside = placeholders(RUN, 4, None, TOOL, "container")
    outside = placeholders(RUN, 4, None, TOOL, "host")
    assert TOOL["mask_output"].format(**inside) == "/output/out_mask.nii.gz"
    assert TOOL["mask_output"].format(**outside) == "out/work/fsl-bet/sub-01/out_mask.nii.gz"
    assert inside["input"] == "/input/sub-01_T1w.nii.gz"


def test_mounts_share_input_read_only_and_skip_missing_tool_dir():
    shared = [(str(host), inside, read_only) for host, inside, read_only in mounts(RUN, TOOL, None)]
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


def test_log_tail_leaves_out_the_command_header(tmp_path):
    log = tmp_path / "run.log"
    log.write_text("docker run ... secret command\n\nline 1\n\nerror: boom\n")
    assert log_tail(log) == "line 1 | error: boom"


def test_failure_status():
    from analysis.skullstrip import failure_status
    assert failure_status(None, timed_out=True) == "timeout"
    assert failure_status(137, timed_out=False) == "oom"
    assert failure_status(1, timed_out=False) == "failed"


def test_requirements_are_mounted_read_only_per_tool():
    shared = mounts(RUN, ANTS, "/data/requirements")
    assert (Path("/data/requirements/ants"), "/requirements", True) in shared
    inside = placeholders(RUN, 8, "/data/requirements", ANTS, "container")
    assert ANTS["command"].format(**inside).endswith("-e /requirements/template.nii.gz")


def test_threads_reach_the_container_environment(tmp_path):
    for engine in ("docker", "apptainer"):
        command = container_command(engine, "img", [], ["tool"], threads=6)
        assert "ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS=6" in command
        assert "OMP_NUM_THREADS=6" in command
