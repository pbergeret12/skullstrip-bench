from pathlib import Path

from invoke import task

# --------------------------------------------------------------------------- #
# Inputs and outputs
#
# Nothing is ever downloaded or copied in: the dataset, the container images
# and the tools' requirements are read where they are, given by flags (or by
# defaults under `inputs:` in invoke.yaml). Everything computed goes to
# --output (default: output_data/). See CLAUDE.md, "No fetch step".
# --------------------------------------------------------------------------- #
PATH_HELP = {
    "bids": "BIDS dataset to benchmark (or `inputs: bids:` in invoke.yaml).",
    "containers": "Folder of container images, .tar and/or .sif (or `inputs: containers:`).",
    "requirements": "Folder with one subfolder per tool holding the files it needs "
                    "(atlases, templates…); only needed by tools that declare `requires`.",
    "output": "Where every result goes (default: output_data/).",
}
SELECTION_HELP = {
    "tools": "Comma-separated tools, e.g. synthstrip,fsl-bet "
             "(default: every compatible image in --containers).",
    "subjects": "Comma-separated subjects, e.g. 10159,sub-10171 (default: all).",
}
SCHEDULERS = ("local", "slurm")


def split_list(value):
    """`"a,b"` → `["a", "b"]`; None stays None (meaning: everything)."""
    return [item.strip() for item in value.split(",")] if value else None


def subject_labels(value):
    """Subjects given as `10159` or `sub-10159`, as bare labels."""
    return [label.removeprefix("sub-") for label in split_list(value) or []]


def output_path(c, output=None):
    return Path(output or c.config.get("output_data_dir")).resolve()


def input_paths(c, bids=None, containers=None, requirements=None, output=None):
    """Every path a check needs, from flags or `inputs:` defaults, made absolute."""
    from invoke.exceptions import Exit

    defaults = c.config.get("inputs") or {}
    bids = bids or defaults.get("bids")
    containers = containers or defaults.get("containers")
    requirements = requirements or defaults.get("requirements")
    if not bids or not containers:
        raise Exit("❌ Give --bids and --containers (or set them under `inputs:` in invoke.yaml).")
    return {
        "bids_dir": Path(bids).resolve(),
        "containers_dir": Path(containers).resolve(),
        "requirements_dir": Path(requirements).resolve() if requirements else None,
        "output_dir": output_path(c, output),
        "tools_dir": Path(c.config.get("tools_dir")).resolve(),
    }


def load_plan(c, output=None):
    """The plan written by run-check, or a clear error."""
    import json

    from invoke.exceptions import Exit

    plan_file = output_path(c, output) / "plan.json"
    if not plan_file.is_file():
        raise Exit(f"❌ No plan in {plan_file.parent}: run `invoke run-check` first.")
    plan = json.loads(plan_file.read_text())
    if not plan["ready"]:
        raise Exit("❌ The plan is not ready: fix what `invoke run-check` reports.")
    return plan


def record_inputs(c, plan):
    """
    Record what the inputs resolved to (paths, git commit of a dataset that is
    a repository) in <output>/MANIFEST.json, through airoh's record_sources.
    """
    from airoh.provenance import record_sources

    c.config.files = {name: {"output_file": plan[key]}
                      for name, key in (("bids", "bids_dir"), ("containers", "containers_dir"),
                                        ("requirements", "requirements_dir"))
                      if plan[key]}
    record_sources(c, output=Path(plan["output_dir"]) / "MANIFEST.json")


# --------------------------------------------------------------------------- #
# Analysis steps
# --------------------------------------------------------------------------- #
@task(help={**PATH_HELP, **SELECTION_HELP,
            "engine": "Force a container engine: docker or apptainer (default: auto).",
            "scheduler": "local (run here) or slurm (cluster jobs: Apptainer, .sif required).",
            "smoke": "Keep only the first T1w (used by run-smoke)."})
def run_check(c, bids=None, containers=None, requirements=None, output=None, tools=None,
              subjects=None, engine=None, scheduler="local", smoke=False):
    """
    Check dataset, tools, images, requirements, engine and output — run nothing.

    The dataset check is shallow (folder layout only, no image is opened), so
    it is fast on any dataset size. Prints a ✔/✘ summary, writes
    <output>/plan.json — the (T1w × tool) runs to execute — and records the
    inputs in <output>/MANIFEST.json. Always re-runs, never skipped: it is
    cheap, and it must see a newly added tool or image. Exits non-zero when
    nothing can run.
    """
    from invoke.exceptions import Exit

    from analysis.check import run_check as check_everything

    if scheduler not in SCHEDULERS:
        raise Exit(f"❌ Unknown --scheduler '{scheduler}' (choose from {', '.join(SCHEDULERS)}).")
    plan = check_everything(input_paths(c, bids, containers, requirements, output),
                            engine=engine, scheduler=scheduler, subjects=split_list(subjects),
                            tools=split_list(tools), smoke=smoke)
    if not plan["ready"]:
        raise Exit("❌ Nothing can run: fix the ✘ above, then `invoke run-check` again.")
    record_inputs(c, plan)
    return plan


@task(help={"containers": PATH_HELP["containers"], "tools": SELECTION_HELP["tools"]})
def prepare_images(c, containers=None, tools=None):
    """
    Build the Apptainer .sif of every tool from its .tar, next to it (once).

    Run on a cluster login node (or in an interactive job) before generating
    Slurm scripts: array tasks only read the .sif, so they never race to
    build the same one.
    """
    from invoke.exceptions import Exit

    from analysis.launcher import engine_is_ready, prepare_image
    from analysis.tool_configs import load_tools

    if not engine_is_ready("apptainer"):
        raise Exit("❌ apptainer not found: on a cluster, `module load apptainer` first.")
    containers_dir = Path(containers or (c.config.get("inputs") or {}).get("containers"))
    configs, _ = load_tools(c.config.get("tools_dir"))
    for name, tool in configs.items():
        if tools and name not in split_list(tools):
            continue
        if (containers_dir / f"{tool['container']}.tar").is_file() or \
                (containers_dir / f"{tool['container']}.sif").is_file():
            print(f"🧱 {name}: {prepare_image('apptainer', tool, containers_dir)}")


@task(help={"output": PATH_HELP["output"], **SELECTION_HELP,
            "retry_failed": "Run again the runs whose record says they failed.",
            "smoke": "Run only the first planned run.",
            "threads": "Cores per tool (default: $SLURM_CPUS_PER_TASK, else all cores).",
            "work_root": "Where tools write their raw outputs (default: <output>/work; "
                         "on a cluster, the node's local disk)."})
def run_skullstrip(c, output=None, subjects=None, tools=None, retry_failed=False, smoke=False,
                   threads=None, work_root=None):
    """
    Execute <output>/plan.json: one container run per (T1w × tool).

    Each run writes its mask to <output>/derivatives/<tool>/, its container
    log to logs/ and its record (status, duration, error) to runs/. The record
    is the "already done" marker — failed runs included, so a slow run that
    ran out of memory is not relaunched every time; use --retry-failed.
    Never fetches anything: it reads the plan, written by run-check.
    """
    import os

    from analysis.skullstrip import run_plan

    threads = int(threads or os.environ.get("SLURM_CPUS_PER_TASK") or os.cpu_count())
    run_plan(load_plan(c, output), subjects=subject_labels(subjects), tools=split_list(tools),
             retry_failed=retry_failed, smoke=smoke, threads=threads, work_root=work_root)


@task(help={"output": PATH_HELP["output"], "subjects": SELECTION_HELP["subjects"]})
def run_figures(c, output=None, subjects=None):
    """
    Draw the report pictures (thumbnail + full size) of every successful run
    that has none yet, cached in <output>/figures/<tool>/. A cluster array
    task draws its own participant's, so the report job only assembles.
    """
    from analysis.report import draw_figures

    output_dir = output_path(c, output)
    draw_figures(output_dir / "runs", output_dir / "figures", subject_labels(subjects))


@task(help={"output": PATH_HELP["output"]})
def run_metrics(c, output=None):
    """
    Write <output>/metrics.csv: per run, mask volume (mL), Dice against the
    consensus of the tools that succeeded on the same T1w, duration, status.

    Always re-runs, like run-check: it takes seconds, and the consensus — hence
    every Dice — changes whenever a run is added, so a cached table would
    silently go stale.
    """
    from analysis.metrics import compute_metrics

    output_dir = output_path(c, output)
    metrics = compute_metrics(output_dir / "runs")
    metrics.to_csv(output_dir / "metrics.csv", index=False)
    print(f"📊 {len(metrics)} runs → {output_dir / 'metrics.csv'}")


@task(help={"output": PATH_HELP["output"]})
def run_report(c, output=None):
    """
    Write <output>/report.html: one row per T1w, one column per tool, each
    cell showing the mask's outline on the T1w, its metrics, and OK / Fail /
    Doubtful buttons with a comment box (notes exported as CSV by the page).

    Draws any missing picture first (see run-figures); the HTML itself is
    rebuilt every time, since it reflects metrics.csv, which always changes.
    Self-contained (images embedded), so the file can be shared alone.
    """
    from invoke.exceptions import Exit

    from analysis.report import build_report

    output_dir = output_path(c, output)
    if not (output_dir / "metrics.csv").is_file():
        raise Exit("❌ No metrics yet: run `invoke run-metrics` first.")
    build_report(
        runs_dir=output_dir / "runs",
        metrics_csv=output_dir / "metrics.csv",
        figures_dir=output_dir / "figures",
        output_html=output_dir / "report.html",
        plausible_volume_ml=c.config.get("report")["plausible_volume_ml"],
    )
    print(f"📄 Report: {output_dir / 'report.html'}")


@task(help={"output": PATH_HELP["output"]})
def run_aggregate(c, output=None):
    """
    Metrics, report, then the provenance record: everything that needs every
    run to be finished. The last step of `run`, and the cluster report job.
    """
    from airoh.provenance import record_run

    output_dir = output_path(c, output)
    run_metrics(c, output=output_dir)
    run_report(c, output=output_dir)
    c.config.manifest_file = str(output_dir / "MANIFEST.json")
    c.config.output_data_dir = str(output_dir)
    record_run(c, output=output_dir / "PROVENANCE.json",
               tasks="run-check,run-skullstrip,run-figures,run-metrics,run-report")


# --------------------------------------------------------------------------- #
# Pipeline
# --------------------------------------------------------------------------- #
@task(help={**PATH_HELP, **SELECTION_HELP,
            "engine": "Force a container engine: docker or apptainer (default: auto).",
            "scheduler": "local: run everything here (default). slurm: run nothing, "
                         "write job scripts in <output>/slurm/ instead.",
            "force": "Delete every computed output first, then run from scratch."})
def run(c, bids=None, containers=None, requirements=None, output=None, tools=None,
        subjects=None, engine=None, scheduler="local", force=False):
    """
    Full pipeline: check → skullstrip → figures → metrics → report.

    With --scheduler slurm, only the check runs here; the rest becomes a
    Slurm job array (one task per participant) plus a report job, written to
    <output>/slurm/ for you to edit (--account, --array) and submit.

    Steps are called directly rather than through `pre=`, so that flags reach
    them. Every step caches by checking whether its output already exists, so
    a repeated `run` does nothing new; `--force` cleans everything first.
    run-check and run-metrics always re-run (see their docstrings).
    """
    if force:
        print("💥 --force: removing every computed output before running")
        clean(c, output=output)
    plan = run_check(c, bids=bids, containers=containers, requirements=requirements,
                     output=output, tools=tools, subjects=subjects, engine=engine,
                     scheduler=scheduler)
    if scheduler == "slurm":
        write_slurm(plan)
        return
    run_skullstrip(c, output=output)
    run_figures(c, output=output)
    run_aggregate(c, output=output)
    print("all analyses completed")


def write_slurm(plan):
    """Write the Slurm scripts and tell the user what to edit and run."""
    import sys

    from analysis.slurm import write_slurm_files

    slurm_dir, resources = write_slurm_files(
        plan, repo_dir=Path(__file__).parent,
        invoke_bin=Path(sys.executable).parent / "invoke", command_line=" ".join(sys.argv))
    print(f"\n📝 Slurm files written to {slurm_dir}/ (nothing submitted):")
    print(f"   jobs.txt              {len(plan['subjects'])} participants, one per line")
    print(f"   skullstrip_array.sh   one task per participant: {resources['cpus']} CPUs, "
          f"{resources['mem_gb']} GB, {resources['minutes']} min")
    print("   skullstrip_report.sh  metrics + report once the array has ended")
    print("   submit.sh             submits both")
    print("\nNext: in both .sh files replace def-CHANGEME with your allocation, choose "
          "--array\n(e.g. 1-20 for a pilot), then run "
          f"{slurm_dir / 'submit.sh'}")


@task(help={**PATH_HELP})
def run_smoke(c, bids=None, containers=None, requirements=None, output=None):
    """
    Smoke test: a minimal end-to-end pass over the whole pipeline.

    One T1w × SynthStrip, run locally. The point is to exercise the plumbing
    quickly, not to produce real results.
    """
    run_check(c, bids=bids, containers=containers, requirements=requirements, output=output,
              tools="synthstrip", smoke=True)
    run_skullstrip(c, output=output, smoke=True)
    run_figures(c, output=output)
    run_aggregate(c, output=output)
    print("✅ Smoke test complete.")


@task(help={
    "skip": "Comma-separated check names to skip.",
    "strict": "Treat warnings as failures.",
})
def verify(c, skip=None, strict=False):
    """
    Check that the code, config, data and docs still agree.

    Run this before committing. It is deliberately NOT part of `run`:
    reproducing results should never depend on documentation hygiene. See
    CLAUDE.md, "Verification", for what each check covers.
    """
    from airoh.verify import verify as airoh_verify
    airoh_verify(c, skip=skip, strict=strict)


# --------------------------------------------------------------------------- #
# Clean
# --------------------------------------------------------------------------- #
def remove(path):
    """Delete a file or a folder, saying so."""
    import shutil

    if path.is_dir():
        shutil.rmtree(path)
    elif path.is_file():
        path.unlink()
    else:
        return
    print(f"🧹 Removed: {path}")


@task(help={"output": PATH_HELP["output"]})
def clean_check(c, output=None):
    """
    Remove <output>/plan.json and the input record MANIFEST.json.
    """
    remove(output_path(c, output) / "plan.json")
    remove(output_path(c, output) / "MANIFEST.json")


@task(help={"output": PATH_HELP["output"],
            "tools": "Comma-separated tools to clean (default: all)."})
def clean_skullstrip(c, output=None, tools=None):
    """
    Remove the outputs of run-skullstrip: derivatives/, runs/, logs/, work/,
    and the report pictures of those masks in figures/ (a picture is only
    valid for the mask it was drawn from).

    With --tools, only those tools' folders go, so their runs (failed ones
    included) are redone on the next `invoke run`.
    """
    output_dir = output_path(c, output)
    for folder in ("derivatives", "runs", "logs", "work", "figures"):
        for tool in split_list(tools) or [""]:
            remove(output_dir / folder / tool)


@task(help={"output": PATH_HELP["output"]})
def clean_metrics(c, output=None):
    """
    Remove <output>/metrics.csv.
    """
    remove(output_path(c, output) / "metrics.csv")


@task(help={"output": PATH_HELP["output"]})
def clean_report(c, output=None):
    """
    Remove <output>/report.html and every cached picture (figures/).
    """
    remove(output_path(c, output) / "report.html")
    remove(output_path(c, output) / "figures")


@task(help={"output": PATH_HELP["output"]})
def clean_slurm(c, output=None):
    """
    Remove the generated Slurm files and job logs (<output>/slurm/).
    """
    remove(output_path(c, output) / "slurm")


@task(help={"output": PATH_HELP["output"]})
def clean(c, output=None):
    """
    Remove all computed outputs.

    The steps are called in the body rather than declared as `pre=`, because a
    `pre=` chain only fires when invoke runs the task from the command line.
    Calling `clean(c)` from Python — which is what `run --force` does — would
    otherwise execute an empty function and silently delete nothing.
    """
    clean_check(c, output=output)
    clean_skullstrip(c, output=output)
    clean_metrics(c, output=output)
    clean_report(c, output=output)
    clean_slurm(c, output=output)
