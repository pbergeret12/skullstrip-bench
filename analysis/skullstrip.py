"""
`run-skullstrip`: execute the plan written by `run-check`, one container run
per (T1w × tool).

This code assumes its inputs are valid — `run-check` already verified them.
Each run gets a single try/except: on failure, the error and the container log
are recorded and the next run starts.
"""
import json
import shlex
import shutil
import time
from pathlib import Path

from analysis.image_checks import check_mask
from analysis.launcher import RunTimeout, prepare_image, run_container
from analysis.postprocess import POSTPROCESSES

OUT_OF_MEMORY_CODES = (137, -9)  # killed by SIGKILL: Docker reports 137, Python -9
LOG_TAIL_LINES = 15


def run_plan(plan, subjects=None, tools=None, retry_failed=False, smoke=False):
    """Run every planned run that is selected and not already done."""
    runs = [run for run in plan["runs"]
            if (not subjects or run["subject"] in subjects)
            and (not tools or run["tool"] in tools)]
    if smoke:
        runs = runs[:1]

    for number, run in enumerate(runs, start=1):
        label = f"[{number}/{len(runs)}] {run['tool']} × {run['stem']}"
        if is_done(run, retry_failed):
            print(f"🫧 {label}: already done")
            continue
        print(f"🧠 {label}: running...")
        record = run_one(run, plan["tools"][run["tool"]], plan["engine"], plan["containers_dir"])
        icon = "✔" if record["status"] == "ok" else "✘"
        print(f"  {icon} {record['status']} in {record['duration_s']:.0f} s"
              + (f": {record['error']}" if record["error"] else ""))


def is_done(run, retry_failed):
    """A run is done once it has a record — even a failed one, unless retrying."""
    record_file = Path(run["record"])
    if not record_file.is_file():
        return False
    return not (retry_failed and json.loads(record_file.read_text())["status"] != "ok")


def run_one(run, tool, engine, containers_dir):
    """Run one tool on one T1w, save its mask and its record, return the record."""
    work_dir = Path(run["work_dir"])
    shutil.rmtree(work_dir, ignore_errors=True)
    work_dir.mkdir(parents=True)
    Path(run["log"]).parent.mkdir(parents=True, exist_ok=True)

    exit_code, error, timed_out = None, None, False
    start = time.monotonic()
    try:
        image = prepare_image(engine, tool, containers_dir)
        command = shlex.split(tool["command"].format(**placeholders(run, tool, "container")))
        exit_code = run_container(engine, image, mounts(run, tool), command, run["log"],
                                  timeout_min=tool.get("timeout_min"))
        if exit_code in OUT_OF_MEMORY_CODES:
            raise RuntimeError("out of memory (exit code 137): give the engine more RAM")
        if exit_code != 0:
            raise RuntimeError(f"exit code {exit_code}: {log_tail(run['log'])}")
        mask_file = Path(tool["mask_output"].format(**placeholders(run, tool, "host")))
        if tool.get("postprocess"):
            mask_file = POSTPROCESSES[tool["postprocess"]](
                mask_file, run["t1w"], work_dir / "mask_postprocessed.nii.gz")
        problem = check_mask(mask_file, run["t1w"])
        if problem:
            raise RuntimeError(problem)
        save_mask(mask_file, run, tool, engine)
    except Exception as exception:  # any failure: record it and move on
        error = str(exception)
        timed_out = isinstance(exception, RunTimeout)

    status = failure_status(exit_code, timed_out) if error else "ok"
    return write_record(run, tool, engine, status, time.monotonic() - start, exit_code, error)


def failure_status(exit_code, timed_out):
    """Why a run failed: `timeout`, `oom` (killed for lack of memory) or `failed`."""
    if timed_out:
        return "timeout"
    return "oom" if exit_code in OUT_OF_MEMORY_CODES else "failed"


def write_record(run, tool, engine, status, duration_s, exit_code, error):
    """Save what happened to a run; the record is also its "already done" marker."""
    record = {"tool": run["tool"], "stem": run["stem"], "subject": run["subject"],
              "status": status, "duration_s": round(duration_s, 1),
              "exit_code": exit_code, "error": error, "engine": engine,
              "image": tool["image"], "t1w": run["t1w"],
              "mask": run["mask"] if status == "ok" else None, "log": run["log"]}
    Path(run["record"]).parent.mkdir(parents=True, exist_ok=True)
    Path(run["record"]).write_text(json.dumps(record, indent=2) + "\n")
    return record


def placeholders(run, tool, side):
    """
    Values of `{input}`, `{mask}`, `{output_prefix}`, `{tool_dir}`, either as
    seen inside the container or as the same files seen from the host.
    """
    if side == "container":
        return {"input": f"/input/{Path(run['t1w']).name}", "mask": "/output/mask.nii.gz",
                "output_prefix": "/output/out", "tool_dir": "/tool"}
    work_dir = Path(run["work_dir"])
    return {"input": run["t1w"], "mask": str(work_dir / "mask.nii.gz"),
            "output_prefix": str(work_dir / "out"), "tool_dir": str(tool_dir(tool))}


def mounts(run, tool):
    """Folders shared with the container: T1w (read-only), work dir, tool annex files."""
    shared = [(Path(run["t1w"]).parent, "/input", True), (run["work_dir"], "/output", False)]
    if tool_dir(tool).is_dir():
        shared.append((tool_dir(tool), "/tool", True))
    return shared


def tool_dir(tool):
    """The tool's annex folder, `tools/<name>/` (it may not exist)."""
    return Path("tools") / tool["name"]


def log_tail(log_file):
    """The last lines the container printed (the log's command header left out)."""
    container_output = Path(log_file).read_text(errors="replace").split("\n\n", 1)[-1]
    lines = [line.strip() for line in container_output.splitlines() if line.strip()]
    return " | ".join(lines[-LOG_TAIL_LINES:])


def save_mask(mask_file, run, tool, engine):
    """Copy the mask into the tool's BIDS derivative dataset."""
    destination = Path(run["mask"])
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(mask_file, destination)

    description = Path(run["derivative_dir"]) / "dataset_description.json"
    if not description.is_file():
        description.write_text(json.dumps({
            "Name": f"{tool['name']} brain masks (skullstrip-bench)",
            "BIDSVersion": "1.9.0",
            "DatasetType": "derivative",
            "GeneratedBy": [{"Name": tool["name"],
                             "Container": {"Type": engine, "Tag": tool["image"]}}],
        }, indent=2) + "\n")
