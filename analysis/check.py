"""
`run-check`: verify everything without launching anything, then write the plan.

The plan (`plan.json`) lists every run to do — one per (T1w × tool) — with all
of its paths already decided. `run-skullstrip` executes it blindly, which is
what keeps the processing code simple: every input it sees was checked here.
"""
import json
import os
from pathlib import Path

from analysis.bids_inputs import derivative_mask_path, find_t1w, list_subjects
from analysis.image_checks import check_t1w
from analysis.launcher import detect_engine, image_status, list_image_files
from analysis.tool_configs import load_tools


def ok(message):
    print(f"  ✔ {message}")


def fail(message):
    print(f"  ✘ {message}")


def run_check(bids_dir, tools_dir, containers_dir, output_dir,
              engine=None, subjects=None, tools=None, smoke=False):
    """Run every check, print a summary, write and return the plan."""
    t1w_images = check_dataset(bids_dir, subjects, smoke)
    engine = check_engine(engine)
    usable_tools = check_tools(tools_dir, containers_dir, engine, tools)
    writable = check_output(output_dir)

    runs = [make_run(tool_name, t1w, output_dir)
            for t1w in t1w_images for tool_name in usable_tools]
    plan = {
        "ready": bool(runs) and engine is not None and writable,
        "engine": engine,
        "containers_dir": str(containers_dir),
        "tools": usable_tools,
        "runs": runs,
    }
    report_plan(plan, output_dir)
    return plan


def check_dataset(bids_dir, subjects=None, smoke=False):
    """Print the dataset checks, return the usable T1w images."""
    print(f"\nDataset  {bids_dir}")
    if not (Path(bids_dir) / "dataset_description.json").is_file():
        fail("dataset_description.json not found: is this a BIDS dataset? (invoke fetch)")
        return []
    ok("dataset_description.json found")

    wanted = [label.removeprefix("sub-") for label in subjects] if subjects else None
    all_t1w = find_t1w(bids_dir)
    for subject in list_subjects(bids_dir):
        if wanted and subject not in wanted:
            continue
        if not any(t1w["entities"]["sub"] == subject for t1w in all_t1w):
            fail(f"sub-{subject}: no T1w, skipped")

    usable = []
    for t1w in all_t1w:
        if wanted and t1w["entities"]["sub"] not in wanted:
            continue
        problem, summary = check_t1w(t1w["path"])
        if problem:
            fail(f"{t1w['stem']}: T1w {problem}, skipped")
        else:
            ok(f"{t1w['stem']}: {summary}")
            usable.append(t1w)
    return usable[:1] if smoke else usable


def check_engine(forced=None):
    """Print which container engine will be used, return it (or None)."""
    print("\nEngine")
    engine, problem = detect_engine(forced)
    if engine:
        ok(f"{engine} ({'forced' if forced else 'auto-detected'})")
    else:
        fail(problem)
    return engine


def check_tools(tools_dir, containers_dir, engine, wanted=None):
    """Print the tool checks, return the configs of the usable tools by name."""
    print(f"\nTools  {tools_dir}  (images in {containers_dir})")
    configs, problems = load_tools(tools_dir)
    for name, problem in problems.items():
        fail(f"{name}: config {problem}")

    usable = {}
    for name, tool in configs.items():
        if wanted and name not in wanted:
            continue
        if engine is None:
            fail(f"{name}: no container engine to run it")
            continue
        ready, message = image_status(engine, tool, containers_dir)
        (ok if ready else fail)(f"{name}: {message}")
        if ready:
            usable[name] = tool

    known_images = {tool["container"] for tool in configs.values()}
    for image in list_image_files(containers_dir):
        if image not in known_images:
            fail(f"{image}: image without a config in {tools_dir}")
    return usable


def check_output(output_dir):
    """Print whether the output folder is writable, return it."""
    print(f"\nOutput  {output_dir}")
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    if os.access(output_dir, os.W_OK):
        ok("writable")
        return True
    fail("not writable")
    return False


def make_run(tool_name, t1w, output_dir):
    """One (T1w × tool) run, with every path it reads or writes."""
    output_dir = Path(output_dir)
    return {
        "tool": tool_name,
        "subject": t1w["entities"]["sub"],
        "stem": t1w["stem"],
        "t1w": t1w["path"],
        "derivative_dir": str(output_dir / "derivatives" / tool_name),
        "mask": str(derivative_mask_path(output_dir / "derivatives", tool_name, t1w)),
        "record": str(output_dir / "runs" / tool_name / f"{t1w['stem']}.json"),
        "log": str(output_dir / "logs" / tool_name / f"{t1w['stem']}.log"),
        "work_dir": str(output_dir / "work" / tool_name / t1w["stem"]),
    }


def report_plan(plan, output_dir):
    """Print the plan summary and write it to `plan.json`."""
    plan_file = Path(output_dir) / "plan.json"
    plan_file.write_text(json.dumps(plan, indent=2) + "\n")
    done = sum(Path(run["record"]).is_file() for run in plan["runs"])
    print(f"\nPlan  {plan_file}")
    print(f"  {len(plan['runs'])} runs "
          f"({len({run['stem'] for run in plan['runs']})} T1w × {len(plan['tools'])} tools), "
          f"{done} already done")
    (ok if plan["ready"] else fail)("ready to run" if plan["ready"] else "nothing can run")
