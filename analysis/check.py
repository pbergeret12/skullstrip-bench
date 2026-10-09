"""
`run-check`: verify everything without launching anything, then write the plan.

The plan (`.skullstrip-bench/plan.json`) lists every run to do, one per
(T1w × tool), with all of its paths already decided (see analysis/layout.py),
plus the inputs it came from. `run-skullstrip`
executes it blindly, which is what keeps the processing code simple.

The dataset check is deliberately shallow: it looks at the folder layout only
and never opens an image, so it takes seconds even on a huge dataset. A broken
T1w simply fails its own run, which is recorded and shown in the report.
"""
import json
import os
import shutil
import subprocess
from pathlib import Path

from analysis.bids_inputs import derivative_mask_path, find_t1w, list_subjects
from analysis.launcher import detect_engine, image_status, list_image_files
from analysis.layout import logs_path, state_path
from analysis.tool_configs import load_tools, missing_requirements

MAX_NAMES_SHOWN = 10


def ok(message):
    print(f"  ✔ {message}")


def fail(message):
    print(f"  ✘ {message}")


def run_check(paths, engine=None, scheduler="local", subjects=None, tools=None, smoke=False):
    """
    Run every check, print a summary, write and return the plan.

    `paths` holds `bids_dir` and `containers_dir` (the user's), `tools_dir`
    and `requirements_dir` (this project's), `output_dir` (the report) and
    `workdir` (logs, and the sbatch script in cluster mode).
    """
    t1w_images = check_dataset(paths["bids_dir"], subjects, smoke)
    engine = check_engine(engine, scheduler)
    usable_tools = check_tools(paths, engine, tools, require_sif=scheduler == "slurm")
    writable = check_output(paths["output_dir"])

    runs = [make_run(tool_name, t1w, paths["output_dir"], paths["workdir"])
            for t1w in t1w_images for tool_name in usable_tools]
    plan = {
        "ready": bool(runs) and engine is not None and writable,
        "skullstrip_bench_version": tool_version(),
        "engine": engine,
        "scheduler": scheduler,
        **{key: str(value) if value else None for key, value in paths.items()},
        "subjects": sorted({f"sub-{t1w['entities']['sub']}" for t1w in t1w_images}),
        "tools": usable_tools,
        "runs": runs,
    }
    report_plan(plan)
    return plan


def tool_version():
    """This tool's version: VERSION in its container, else the checkout's git commit."""
    project_dir = Path(__file__).resolve().parents[1]
    if (project_dir / "VERSION").is_file():
        return (project_dir / "VERSION").read_text().strip()
    result = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=project_dir,
                            capture_output=True, text=True)
    return result.stdout.strip() or "unknown"


def check_dataset(bids_dir, subjects=None, smoke=False):
    """Print the (shallow) dataset checks, return the T1w images to process."""
    print(f"\nDataset  {bids_dir}")
    if not (Path(bids_dir) / "dataset_description.json").is_file():
        fail("dataset_description.json not found: is --bids a BIDS dataset?")
        return []
    ok("dataset_description.json found")

    wanted = {label.removeprefix("sub-") for label in subjects} if subjects else None
    all_subjects = list_subjects(bids_dir)
    if wanted:
        unknown = sorted(wanted - set(all_subjects))
        if unknown:
            fail(f"unknown subjects ignored: {names(unknown)}")
        all_subjects = [subject for subject in all_subjects if subject in wanted]
    t1w_images = [t1w for t1w in find_t1w(bids_dir) if t1w["entities"]["sub"] in all_subjects]

    with_t1w = {t1w["entities"]["sub"] for t1w in t1w_images}
    sessions = {t1w["entities"].get("ses") for t1w in t1w_images} - {None}
    (ok if t1w_images else fail)(
        f"{len(with_t1w)} subjects, {len(t1w_images)} T1w images"
        + (f", {len(sessions)} sessions" if sessions else ""))
    without_t1w = [subject for subject in all_subjects if subject not in with_t1w]
    if without_t1w:
        fail(f"{len(without_t1w)} subjects without T1w, skipped: {names(without_t1w)}")
    return t1w_images[:1] if smoke else t1w_images


def names(labels):
    """A readable, bounded list of names: `a, b, c, … (+12)`."""
    shown = ", ".join(labels[:MAX_NAMES_SHOWN])
    hidden = len(labels) - MAX_NAMES_SHOWN
    return shown + (f", … (+{hidden})" if hidden > 0 else "")


def check_engine(forced=None, scheduler="local"):
    """Print which container engine will be used, return it (or None)."""
    print("\nEngine")
    if scheduler == "slurm":
        # Jobs run on compute nodes, where only Apptainer exists. It may not be
        # on PATH here: the job script loads it.
        if forced == "docker":
            fail("Docker is not available on clusters: use --engine apptainer (or omit it)")
            return None
        found = "found here" if shutil.which("apptainer") else \
            "not on PATH here; the job script runs `module load apptainer`"
        ok(f"apptainer (cluster jobs; {found})")
        return "apptainer"
    engine, problem = detect_engine(forced)
    if engine:
        ok(f"{engine} ({'forced' if forced else 'auto-detected'})")
    else:
        fail(problem)
    return engine


def check_tools(paths, engine, wanted=None, require_sif=False):
    """
    Print the tool checks, return the configs of the usable tools by name.

    Without `wanted`, every image in the containers folder that has a config
    in `tools/` is used; other images are reported as not compatible.
    """
    tools_dir, containers_dir = paths["tools_dir"], paths["containers_dir"]
    print(f"\nTools  {tools_dir}  (images in {containers_dir})")
    configs, problems = load_tools(tools_dir)
    for name, problem in problems.items():
        fail(f"{name}: config {problem}")

    by_image = {tool["container"]: name for name, tool in configs.items()}
    if wanted:
        candidates = [name for name in wanted if name in configs]
        for name in sorted(set(wanted) - set(configs)):
            fail(f"{name}: unknown tool (no {name}.yaml in {tools_dir})")
    else:
        candidates = []
        for image in list_image_files(containers_dir):
            if image in by_image:
                candidates.append(by_image[image])
            else:
                fail(f"{image}: not compatible (no config in {tools_dir}), skipped")

    usable = {}
    for name in sorted(candidates):
        tool = configs[name]
        if usable_tool(tool, engine, paths, require_sif):
            usable[name] = tool
    return usable


def usable_tool(tool, engine, paths, require_sif):
    """Print and return whether one tool can run: requirements, then image."""
    missing = missing_requirements(tool, paths["requirements_dir"])
    if missing:
        fail(f"{tool['name']}: files bundled with skullstrip-bench are missing from "
             f"{paths['requirements_dir']}/{tool['name']}/ ({', '.join(missing)}): "
             "this installation is incomplete")
        return False
    if engine is None:
        fail(f"{tool['name']}: no container engine to run it")
        return False
    ready, message = image_status(engine, tool, paths["containers_dir"], require_sif)
    (ok if ready else fail)(f"{tool['name']}: {message}")
    return ready


def check_output(output_dir):
    """Print whether the output folder is writable, return it."""
    print(f"\nOutput  {output_dir}")
    state_path(output_dir).mkdir(parents=True, exist_ok=True)
    if os.access(output_dir, os.W_OK):
        ok("writable")
        return True
    fail("not writable")
    return False


def make_run(tool_name, t1w, output_dir, workdir):
    """
    One (T1w × tool) run, with every path it reads or writes: its logs go to
    the working directory, its mask, record and scratch folder are internal
    state of the output folder.
    """
    stem = t1w["stem"]
    return {
        "tool": tool_name,
        "subject": t1w["entities"]["sub"],
        "stem": stem,
        "t1w": t1w["path"],
        "mask": str(derivative_mask_path(state_path(output_dir, "masks"), tool_name, t1w)),
        "record": str(state_path(output_dir, "runs", tool_name, f"{stem}.json")),
        "log": str(logs_path(workdir, tool_name, f"{stem}.log")),
        "err": str(logs_path(workdir, tool_name, f"{stem}.err")),
        "work_dir": str(state_path(output_dir, "work", tool_name, stem)),
    }


def report_plan(plan):
    """Print the plan summary and write it to `.skullstrip-bench/plan.json`."""
    plan_file = state_path(plan["output_dir"], "plan.json")
    plan_file.write_text(json.dumps(plan, indent=2) + "\n")
    done = sum(Path(run["record"]).is_file() for run in plan["runs"])
    print(f"\nPlan  {plan_file}")
    print(f"  {len(plan['runs'])} runs "
          f"({len({run['stem'] for run in plan['runs']})} T1w × {len(plan['tools'])} tools), "
          f"{done} already done")
    (ok if plan["ready"] else fail)("ready to run" if plan["ready"] else "nothing can run")
