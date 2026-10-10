"""
`run-skullstrip`: execute the plan written by `run-check`, one container run
per (T1w × tool).

This code assumes its inputs are valid — `run-check` already verified them.
Each run gets a single try/except: on failure, the error and the container log
are recorded and the next run starts.

The same code runs locally and inside a cluster array task; only `threads`
and `work_root` change (the cores Slurm granted, the node's local disk).
"""
import json
import shlex
import shutil
import time
from pathlib import Path

from analysis.image_checks import check_mask
from analysis.launcher import RunTimeout, prepare_image, run_container
from analysis.postprocess import POSTPROCESSES
from analysis.reconall import LICENSE_FILE, prepare_input

OUT_OF_MEMORY_CODES = (137, -9)  # killed by SIGKILL: Docker reports 137, Python -9
LOG_TAIL_LINES = 15


def run_plan(plan, subjects=None, tools=None, retry_failed=False, smoke=False,
             threads=1, work_root=None):
    """
    Run every planned run that is selected and not already done.

    `work_root`, if given, replaces the plan's work folders (e.g. a cluster
    node's local disk); `threads` is passed to every tool.
    """
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
        if work_root:
            run = {**run, "work_dir": str(Path(work_root) / run["tool"] / run["stem"])}
        record = run_one(run, plan["tools"][run["tool"]], plan, threads)
        icon = "✔" if record["status"] == "ok" else "✘"
        print(f"  {icon} {record['status']} in {record['duration_s']:.0f} s"
              + (f": {record['error']}" if record["error"] else ""))


def is_done(run, retry_failed):
    """A run is done once it has a record — even a failed one, unless retrying."""
    record_file = Path(run["record"])
    if not record_file.is_file():
        return False
    return not (retry_failed and json.loads(record_file.read_text())["status"] != "ok")


def run_one(run, tool, plan, threads=1):
    """
    Run one tool on one T1w, save its mask and its record, return the record.
    The tool's raw outputs live in a scratch folder deleted afterwards; what
    happened is in the run's .log and .err files.
    """
    engine = plan["engine"]
    work_dir = Path(run["work_dir"])
    shutil.rmtree(work_dir, ignore_errors=True)
    work_dir.mkdir(parents=True)

    exit_code, error, timed_out = None, None, False
    start = time.monotonic()
    try:
        image = prepare_image(engine, tool, plan["containers_dir"])
        host_values = placeholders(run, threads, plan, tool, "host")
        if run.get("refines"):
            prepare_input(run, f"{host_values['output_prefix']}_bids")
        values = placeholders(run, threads, plan, tool, "container")
        command = shlex.split(tool["command"].format(**values))
        exit_code = run_container(engine, image, mounts(run, tool, plan), command,
                                  run["log"], run["err"],
                                  timeout_min=tool.get("timeout_min"), threads=threads)
        if exit_code in OUT_OF_MEMORY_CODES:
            raise RuntimeError("out of memory (exit code 137): give the engine more RAM")
        if exit_code != 0:
            raise RuntimeError(f"exit code {exit_code}: {log_tail(run)}")
        mask_file = Path(tool["mask_output"].format(**host_values))
        if tool.get("postprocess"):
            mask_file = POSTPROCESSES[tool["postprocess"]](
                mask_file, run["t1w"], work_dir / "mask_postprocessed.nii.gz")
        problem = check_mask(mask_file, run["t1w"])
        if problem:
            raise RuntimeError(problem)
        save_mask(mask_file, run)
    except Exception as exception:  # any failure: record it and move on
        error = str(exception)
        timed_out = isinstance(exception, RunTimeout)
    finally:
        remove_scratch(work_dir)

    status = failure_status(exit_code, timed_out) if error else "ok"
    duration_s = time.monotonic() - start
    note_outcome(run, status, duration_s, error)
    return write_record(run, tool, engine, status, duration_s, exit_code, error)


def remove_scratch(work_dir):
    """Delete a run's scratch folder, and its parents up to `work/` once empty."""
    shutil.rmtree(work_dir, ignore_errors=True)
    for parent in (work_dir.parent, work_dir.parent.parent):
        try:
            parent.rmdir()   # only succeeds when empty: other runs may be using it
        except OSError:
            break


def note_outcome(run, status, duration_s, error):
    """End the run's .log with its status, and its .err with why it failed."""
    Path(run["log"]).parent.mkdir(parents=True, exist_ok=True)
    with open(run["log"], "a") as log:
        log.write(f"# skullstrip-bench: {status} in {duration_s:.0f} s\n")
    if error:
        with open(run["err"], "a") as err:
            err.write(f"skullstrip-bench: run {status}: {error}\n")


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
              "image": tool["image"], "t1w": run["t1w"], "refines": run.get("refines"),
              "mask": run["mask"] if status == "ok" else None,
              "log": run["log"], "err": run["err"]}
    Path(run["record"]).parent.mkdir(parents=True, exist_ok=True)
    Path(run["record"]).write_text(json.dumps(record, indent=2) + "\n")
    return record


def placeholders(run, threads, plan, tool, side):
    """
    Values of `{input}`, `{mask}`, `{output_prefix}`, `{requirements}`,
    `{license}` and `{threads}`, either as seen inside the container or as the
    same files seen from the host.
    """
    if side == "container":
        return {"input": f"/input/{Path(run['t1w']).name}", "mask": "/output/mask.nii.gz",
                "output_prefix": "/output/out", "requirements": "/requirements",
                "license": f"/license/{LICENSE_FILE}", "threads": threads}
    work_dir = Path(run["work_dir"])
    return {"input": run["t1w"], "mask": str(work_dir / "mask.nii.gz"),
            "output_prefix": str(work_dir / "out"),
            "requirements": str(tool_requirements(plan.get("requirements_dir"), tool)),
            "license": str(Path(plan.get("containers_dir") or ".") / LICENSE_FILE),
            "threads": threads}


def mounts(run, tool, plan):
    """
    Folders shared with the container: T1w (read-only), work dir, and if the
    tool needs them, its requirements and the FreeSurfer license (read-only).
    """
    shared = [(Path(run["t1w"]).parent, "/input", True), (run["work_dir"], "/output", False)]
    if tool["requires"]:
        shared.append((tool_requirements(plan.get("requirements_dir"), tool),
                       "/requirements", True))
    if "{license}" in tool["command"]:
        shared.append((plan["containers_dir"], "/license", True))
    return shared


def tool_requirements(requirements_dir, tool):
    """The tool's own requirements folder, `<requirements>/<tool>/`."""
    return Path(requirements_dir or ".") / tool["name"]


def log_tail(run):
    """The last lines of the container's errors (or of its output, if it wrote none)."""
    for log_file in (run["err"], run["log"]):
        lines = [line.strip() for line in Path(log_file).read_text(errors="replace").splitlines()
                 if line.strip() and not line.startswith("# ")]
        if lines:
            return " | ".join(lines[-LOG_TAIL_LINES:])
    return "no output"


def save_mask(mask_file, run):
    """Keep the validated mask in the internal state (metrics and pictures need it)."""
    destination = Path(run["mask"])
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(mask_file, destination)
