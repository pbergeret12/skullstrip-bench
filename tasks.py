from pathlib import Path

from invoke import task

# --------------------------------------------------------------------------- #
# Inputs and outputs
#
# Nothing is ever downloaded or copied in: the user brings only the BIDS
# dataset and the container images, read where they are, given by flags (or
# by defaults under `inputs:` in invoke.yaml). What a supported tool needs
# besides its image (e.g. ANTs' template) ships with this project, in
# container_requirements/. Everything computed goes to
# --output (default: output_data/): report/ and logs/ for the user, the rest
# in the hidden .skullstrip-bench/ (see analysis/layout.py and CLAUDE.md,
# "No fetch step").
# --------------------------------------------------------------------------- #
PATH_HELP = {
    "bids": "BIDS dataset to benchmark (or `inputs: bids:` in invoke.yaml).",
    "containers": "Folder of container images, .tar and/or .sif (or `inputs: containers:`).",
    "output": "Where every result goes (default: output_data/).",
}
SELECTION_HELP = {
    "tools": "Comma-separated tools, e.g. synthstrip,fsl-bet "
             "(default: every compatible image in --containers).",
    "subjects": "Comma-separated subjects, e.g. 10159,sub-10171 (default: all).",
}
SCHEDULERS = ("local", "slurm")
PROJECT_DIR = Path(__file__).resolve().parent   # also inside the tool's container


def tools_dir(c):
    """The tool configs, found next to this file whatever the working directory."""
    return PROJECT_DIR / c.config.get("tools_dir")


def split_list(value):
    """`"a,b"` → `["a", "b"]`; None stays None (meaning: everything)."""
    return [item.strip() for item in value.split(",")] if value else None


def subject_labels(value):
    """Subjects given as `10159` or `sub-10159`, as bare labels."""
    return [label.removeprefix("sub-") for label in split_list(value) or []]


def output_path(c, output=None):
    return Path(output or c.config.get("output_data_dir")).resolve()


def state(c, output, *parts):
    """A path in the output's hidden internal state folder."""
    from analysis.layout import state_path
    return state_path(output_path(c, output), *parts)


def input_paths(c, bids=None, containers=None, output=None):
    """
    Every path a check needs, made absolute: the user's dataset and images
    (flags or `inputs:` defaults), this project's tool configs and their
    bundled requirements, and the output folder.
    """
    from invoke.exceptions import Exit

    defaults = c.config.get("inputs") or {}
    bids = bids or defaults.get("bids")
    containers = containers or defaults.get("containers")
    if not bids or not containers:
        raise Exit("❌ Give --bids and --containers (or set them under `inputs:` in invoke.yaml).")
    return {
        "bids_dir": Path(bids).resolve(),
        "containers_dir": Path(containers).resolve(),
        "requirements_dir": PROJECT_DIR / c.config.get("requirements_dir"),
        "output_dir": output_path(c, output),
        "tools_dir": tools_dir(c),
    }


def load_plan(c, output=None):
    """The plan written by run-check, or a clear error."""
    import json

    from invoke.exceptions import Exit

    plan_file = state(c, output, "plan.json")
    if not plan_file.is_file():
        raise Exit(f"❌ No plan in {plan_file.parent}: run `invoke run-check` first.")
    plan = json.loads(plan_file.read_text())
    if not plan["ready"]:
        raise Exit("❌ The plan is not ready: fix what `invoke run-check` reports.")
    return plan


def record_inputs(c, plan):
    """
    Record what the inputs resolved to (paths, git commit of a dataset that is
    a repository) in the internal MANIFEST.json, through airoh's record_sources.
    """
    from airoh.provenance import record_sources

    c.config.files = {name: {"output_file": plan[key]}
                      for name, key in (("bids", "bids_dir"), ("containers", "containers_dir"))}
    record_sources(c, output=state(c, plan["output_dir"], "MANIFEST.json"))


# --------------------------------------------------------------------------- #
# Analysis steps
# --------------------------------------------------------------------------- #
@task(help={**PATH_HELP, **SELECTION_HELP,
            "engine": "Force a container engine: docker or apptainer (default: auto).",
            "scheduler": "local (run here) or slurm (cluster jobs: Apptainer, .sif required).",
            "smoke": "Keep only the first T1w (used by run-smoke)."})
def run_check(c, bids=None, containers=None, output=None, tools=None,
              subjects=None, engine=None, scheduler="local", smoke=False):
    """
    Check dataset, tools, images, requirements, engine and output — run nothing.

    The dataset check is shallow (folder layout only, no image is opened), so
    it is fast on any dataset size. Prints a ✔/✘ summary, writes the plan of
    (T1w × tool) runs to execute and records the inputs, both in the output's
    hidden .skullstrip-bench/ folder. Always re-runs, never skipped: it is
    cheap, and it must see a newly added tool or image. Exits non-zero when
    nothing can run.
    """
    from invoke.exceptions import Exit

    from analysis.check import run_check as check_everything

    if scheduler not in SCHEDULERS:
        raise Exit(f"❌ Unknown --scheduler '{scheduler}' (choose from {', '.join(SCHEDULERS)}).")
    plan = check_everything(input_paths(c, bids, containers, output),
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
    configs, _ = load_tools(tools_dir(c))
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
            "work_root": "Where tools write their raw outputs, deleted after each run "
                         "(default: inside the output's hidden state; on a cluster, the "
                         "node's local disk)."})
def run_skullstrip(c, output=None, subjects=None, tools=None, retry_failed=False, smoke=False,
                   threads=None, work_root=None):
    """
    Execute the plan: one container run per (T1w × tool).

    Each run writes its container output to <output>/logs/<tool>/<stem>.log
    and its errors to .err; its mask and its record (status, duration,
    error) go to the hidden internal state, and its raw outputs are deleted.
    The record is the "already done" marker — failed runs included, so a slow run that
    ran out of memory is not relaunched every time; use --retry-failed.
    Never fetches anything: it reads the plan, written by run-check.
    """
    import os

    from analysis.skullstrip import run_plan

    threads = int(threads or os.environ.get("SLURM_CPUS_PER_TASK") or os.cpu_count())
    run_plan(load_plan(c, output), subjects=subject_labels(subjects), tools=split_list(tools),
             retry_failed=retry_failed, smoke=smoke, threads=threads, work_root=work_root)


def planned_subjects(plan, subjects=None):
    """Subject labels to update: the given ones, else every planned participant."""
    return subject_labels(subjects) or [label.removeprefix("sub-") for label in plan["subjects"]]


@task(help={"output": PATH_HELP["output"], "subjects": SELECTION_HELP["subjects"]})
def run_metrics(c, output=None, subjects=None):
    """
    Update <output>/report/metrics.csv: per run, mask volume (mL), Dice
    against the consensus of the selected tools that succeeded on the same
    T1w, duration, status.

    Each participant has its own part (internal state), rewritten here;
    metrics.csv is then rebuilt from every part. Always re-runs, like
    run-check: it takes seconds per participant.
    """
    from analysis.layout import report_path, state_path
    from analysis.metrics import update_metrics

    plan = load_plan(c, output)
    output_dir = Path(plan["output_dir"])
    metrics_csv = report_path(output_dir, "metrics.csv")
    parts = update_metrics(state_path(output_dir, "runs"), state_path(output_dir, "metrics_parts"),
                           metrics_csv, planned_subjects(plan, subjects),
                           tools=list(plan["tools"]))
    print(f"📊 {len(parts)} participants → {metrics_csv}")


@task(help={"output": PATH_HELP["output"], "subjects": SELECTION_HELP["subjects"]})
def run_report(c, output=None, subjects=None):
    """
    Update <output>/report/report.html: one row per T1w, one column per tool, each
    cell showing the mask's outline on the T1w, its metrics, and Good / Bad /
    Uncertain buttons with a comment box (ratings exported as CSV by the page).

    Each participant has its own part (internal state, its pictures
    embedded), rewritten here after drawing its missing pictures (cached in
    report/figures/); report.html is then rebuilt from every part. It can be opened
    at any time: reloading shows the participants finished since.
    """
    from analysis.report import update_report

    plan = load_plan(c, output)
    parts = update_report(plan, planned_subjects(plan, subjects),
                          c.config.get("report")["plausible_volume_ml"])
    print(f"📄 {len(parts)} / {len(plan['subjects'])} participants → "
          f"{Path(plan['output_dir']) / 'report' / 'report.html'}")


@task(help={"output": PATH_HELP["output"], "subjects": SELECTION_HELP["subjects"]})
def run_update(c, output=None, subjects=None):
    """
    Metrics, then report, for some participants (default: all): what a
    participant's job runs once its runs are done, so the report grows as
    participants finish.
    """
    run_metrics(c, output=output, subjects=subjects)
    run_report(c, output=output, subjects=subjects)


def record_provenance(c, output=None):
    """
    Write the internal PROVENANCE.json (airoh's record_run): checksums of the
    visible outputs (report/, logs/), the environment, the inputs consumed.
    """
    from airoh.provenance import record_run

    c.config.manifest_file = str(state(c, output, "MANIFEST.json"))
    c.config.output_data_dir = str(output_path(c, output))
    record_run(c, output=state(c, output, "PROVENANCE.json"),
               tasks="run-check,run-skullstrip,run-metrics,run-report")


@task(help={"output": PATH_HELP["output"]})
def run_aggregate(c, output=None):
    """
    Rebuild metrics and report for every participant, then the provenance
    record. The cluster report job, once the array has ended: it makes the
    final files complete even if two participants' updates overlapped.
    """
    run_update(c, output=output)
    record_provenance(c, output=output)


# --------------------------------------------------------------------------- #
# Pipeline
# --------------------------------------------------------------------------- #
@task(help={**PATH_HELP, **SELECTION_HELP,
            "engine": "Force a container engine: docker or apptainer (default: auto).",
            "scheduler": "local: run everything here (default). slurm: run nothing, "
                         "write job scripts in <output>/slurm/ instead.",
            "force": "Delete every computed output first, then run from scratch."})
def run(c, bids=None, containers=None, output=None, tools=None,
        subjects=None, engine=None, scheduler="local", force=False):
    """
    Full pipeline: check, then participant by participant: skullstrip runs,
    metrics, report update (the report grows as participants finish).

    With --scheduler slurm, only the check runs here; the rest becomes a
    Slurm job array (one task per participant) plus a report job, written to
    <output>/slurm/ for you to edit (--account, --array) and submit.

    Steps are called directly rather than through `pre=`, so that flags reach
    them. Every step caches by checking whether its output already exists, so
    a repeated `run` does nothing new; `--force` cleans everything first.
    run-check, run-metrics and run-report always re-run (see their docstrings).
    """
    if force:
        print("💥 --force: removing every computed output before running")
        clean(c, output=output)
    plan = run_check(c, bids=bids, containers=containers, output=output, tools=tools,
                     subjects=subjects, engine=engine, scheduler=scheduler)
    if scheduler == "slurm":
        write_slurm(plan)
        return
    for subject in plan["subjects"]:
        run_skullstrip(c, output=output, subjects=subject)
        run_update(c, output=output, subjects=subject)
    record_provenance(c, output=output)
    print("all analyses completed")


def write_slurm(plan):
    """Write the Slurm scripts and tell the user what to edit and run."""
    import sys

    from analysis.slurm import write_slurm_files

    slurm_dir, resources = write_slurm_files(
        plan, repo_dir=PROJECT_DIR, invoke_bin=Path(sys.executable).parent / "invoke",
        command_line=" ".join(sys.argv))
    print(f"\n📝 Slurm files written to {slurm_dir}/ (nothing submitted):")
    print(f"   jobs.txt              {len(plan['subjects'])} participants, one per line")
    print(f"   skullstrip_array.sh   one task per participant: {resources['cpus']} CPUs, "
          f"{resources['mem_gb']} GB, {resources['minutes']} min")
    print("   skullstrip_report.sh  final rebuild of metrics + report once the array has ended")
    print("   submit.sh             submits both")
    print(f"   job logs: {Path(plan['output_dir']) / 'logs' / 'slurm'}/ (.log and .err)")
    print(f"\nNext: in skullstrip_array.sh and skullstrip_report.sh, replace def-CHANGEME "
          f"with your allocation\n(and narrow --array if you want fewer than all "
          f"{len(plan['subjects'])} participants), then run {slurm_dir / 'submit.sh'}")


@task(help={**PATH_HELP})
def run_smoke(c, bids=None, containers=None, output=None):
    """
    Smoke test: a minimal end-to-end pass over the whole pipeline.

    One T1w × SynthStrip, run locally. The point is to exercise the plumbing
    quickly, not to produce real results.
    """
    run_check(c, bids=bids, containers=containers, output=output,
              tools="synthstrip", smoke=True)
    run_skullstrip(c, output=output, smoke=True)
    run_aggregate(c, output=output)
    print("✅ Smoke test complete.")


@task(help={"output_dir": "Where to write the image archive (default: current folder).",
            "version": "Image version (default: the git commit, with -dirty if modified)."})
def build_image(c, output_dir=".", version=None):
    """
    Build the tool's own container with Docker and save it as a .tar.

    Run on a machine with internet and Docker (e.g. your laptop). Copy the
    .tar to the cluster and convert it once:
    `apptainer build skullstrip-bench.sif docker-archive://skullstrip-bench_<version>.tar`.
    """
    if version is None:
        commit = c.run("git rev-parse --short HEAD", hide=True).stdout.strip()
        dirty = c.run("git status --porcelain", hide=True).stdout.strip()
        version = commit + ("-dirty" if dirty else "")
    archive = Path(output_dir).resolve() / f"skullstrip-bench_{version}.tar"
    with c.cd(str(PROJECT_DIR)):
        c.run(f"docker build --platform linux/amd64 --build-arg VERSION={version} "
              f"-t skullstrip-bench:{version} .")
    c.run(f"docker save -o {archive} skullstrip-bench:{version}")
    print(f"📦 {archive}")


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
    Remove the plan and the input record (internal state).
    """
    remove(state(c, output, "plan.json"))
    remove(state(c, output, "MANIFEST.json"))


@task(help={"output": PATH_HELP["output"],
            "tools": "Comma-separated tools to clean (default: all)."})
def clean_skullstrip(c, output=None, tools=None):
    """
    Remove the outputs of run-skullstrip: logs, and in the internal state the
    masks, run records and scratch folders. Also the report pictures of those
    masks (a picture is only valid for the mask it was drawn from) and the
    per-participant parts of metrics and report, which summarize these runs.

    With --tools, only those tools' files go, so their runs (failed ones
    included) are redone on the next `invoke run`.
    """
    from analysis.layout import logs_path, report_path

    output_dir = output_path(c, output)
    for tool in split_list(tools) or [""]:
        for folder in (logs_path(output_dir), report_path(output_dir, "figures"),
                       state(c, output, "masks"), state(c, output, "runs"),
                       state(c, output, "work")):
            remove(folder / tool)
    remove(state(c, output, "metrics_parts"))
    remove(state(c, output, "report_parts"))


@task(help={"output": PATH_HELP["output"]})
def clean_metrics(c, output=None):
    """
    Remove report/metrics.csv and its per-participant parts.
    """
    remove(output_path(c, output) / "report" / "metrics.csv")
    remove(state(c, output, "metrics_parts"))


@task(help={"output": PATH_HELP["output"]})
def clean_report(c, output=None):
    """
    Remove report/report.html, its pictures and its per-participant parts.
    """
    remove(output_path(c, output) / "report" / "report.html")
    remove(output_path(c, output) / "report" / "figures")
    remove(state(c, output, "report_parts"))


@task(help={"output": PATH_HELP["output"]})
def clean_slurm(c, output=None):
    """
    Remove the generated Slurm scripts and the jobs' logs.
    """
    remove(output_path(c, output) / "slurm")
    remove(output_path(c, output) / "logs" / "slurm")


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
