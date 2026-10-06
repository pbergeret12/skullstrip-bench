from pathlib import Path

from invoke import task


# --------------------------------------------------------------------------- #
# Fetch
# --------------------------------------------------------------------------- #
def link_asset(c, name, source=None, copy=False):
    """
    Link (or copy) an existing folder into source_data/ — never a download.

    Without a source, an asset that is already linked is left alone, so a bare
    `invoke fetch` (as `run-smoke` does) works once the links exist.
    """
    from airoh.acquisition import fetch_data
    from invoke.exceptions import Exit

    entry = c.config.get("files")[name]
    destination = Path(entry["output_file"])
    if not (source or entry.get("source")):
        if destination.exists():
            print(f"🫧 Skipping {name}: {destination} already present")
            return
        raise Exit(f"❌ No '{name}' yet: run `invoke fetch-{name} --source /path`.")
    fetch_data(c, name, source=source, copy=copy)


@task(help={
    "source": "Path to an existing BIDS dataset to symlink into source_data/bids.",
    "copy": "Copy the dataset instead of symlinking it.",
})
def fetch_bids(c, source=None, copy=False):
    """
    Make the BIDS dataset available as source_data/bids (symlink, no download).
    """
    link_asset(c, "bids", source=source, copy=copy)


@task(help={
    "source": "Path to the folder of container images (.tar / .sif) to symlink.",
    "copy": "Copy the folder instead of symlinking it.",
})
def fetch_containers(c, source=None, copy=False):
    """
    Make the container images available as source_data/containers (symlink).

    A symlink, so the .sif files Apptainer builds land in the real folder and
    are kept for the next run.
    """
    link_asset(c, "containers", source=source, copy=copy)


ANTS_TEMPLATE_FILES = ("T_template0.nii.gz",
                       "T_template0_BrainCerebellumProbabilityMask.nii.gz",
                       "T_template0_BrainCerebellumRegistrationMask.nii.gz")


@task
def fetch_ants_template(c):
    """
    Download the OASIS template for ANTs and unzip what antsBrainExtraction.sh
    needs into tools/ants/template/ (gitignored). Skipped once present.
    """
    import zipfile

    from airoh.acquisition import fetch_data

    zip_file = Path(c.config.get("files")["ants_template"]["output_file"])
    template_dir = zip_file.parent / "template"
    if all((template_dir / name).is_file() for name in ANTS_TEMPLATE_FILES):
        print(f"🫧 Skipping ants_template: {template_dir} already present")
        return
    zip_file.parent.mkdir(parents=True, exist_ok=True)
    fetch_data(c, "ants_template")
    template_dir.mkdir(exist_ok=True)
    with zipfile.ZipFile(zip_file) as archive:
        for name in ANTS_TEMPLATE_FILES:
            member = f"MICCAI2012-Multi-Atlas-Challenge-Data/{name}"
            (template_dir / name).write_bytes(archive.read(member))
    print(f"✅ ANTs template ready in {template_dir}")


@task(help={
    "bids_source": "Path to an existing BIDS dataset to symlink.",
    "containers_source": "Path to the folder of container images to symlink.",
    "copy": "Copy source data instead of symlinking it.",
})
def fetch(c, bids_source=None, containers_source=None, copy=False):
    """
    Retrieve all data assets. Each asset has its own fetch-{name} task; this
    umbrella task routes a per-asset --{name}-source flag to the matching one.

    Records what each asset actually resolved to in source_data/MANIFEST.json,
    so the inputs a later run consumed stay identifiable — including the commit
    of a symlinked external checkout. See CLAUDE.md, "Recording asset versions".
    """
    from airoh.provenance import record_sources

    fetch_bids(c, source=bids_source, copy=copy)
    fetch_containers(c, source=containers_source, copy=copy)
    fetch_ants_template(c)
    record_sources(c)


# --------------------------------------------------------------------------- #
# Analysis steps
# --------------------------------------------------------------------------- #
def split_list(value):
    """`"a,b"` → `["a", "b"]`; None stays None (meaning: everything)."""
    return [item.strip() for item in value.split(",")] if value else None


@task(help={
    "containers": "Folder of container images (default: source_data/containers).",
    "engine": "Force a container engine: docker or apptainer (default: auto).",
    "subjects": "Comma-separated subjects to include, e.g. 10159,sub-10171.",
    "tools": "Comma-separated tools to include, e.g. synthstrip,fsl-bet.",
    "smoke": "Keep only the first T1w (used by run-smoke).",
})
def run_check(c, containers=None, engine=None, subjects=None, tools=None, smoke=False):
    """
    Check the dataset, tools, images, engine and output folder — run nothing.

    Prints a ✔/✘ summary and writes output_data/plan.json, the list of
    (T1w × tool) runs that run-skullstrip will execute. Always re-runs, never
    skipped: it is cheap, and it must see a newly added tool or image. Exits
    non-zero when nothing can run.
    """
    from invoke.exceptions import Exit

    from analysis.check import run_check as check_everything

    plan = check_everything(
        bids_dir=Path(c.config.get("files")["bids"]["output_file"]),
        tools_dir=Path(c.config.get("tools_dir")),
        containers_dir=Path(containers or c.config.get("files")["containers"]["output_file"]),
        output_dir=Path(c.config.get("output_data_dir")),
        engine=engine, subjects=split_list(subjects), tools=split_list(tools), smoke=smoke,
    )
    if not plan["ready"]:
        raise Exit("❌ Nothing can run: fix the ✘ above, then `invoke run-check` again.")


@task(help={
    "subjects": "Comma-separated subjects to run, e.g. 10159,10171 (default: all planned).",
    "tools": "Comma-separated tools to run, e.g. synthstrip (default: all planned).",
    "retry_failed": "Run again the runs whose record says they failed.",
    "smoke": "Run only the first planned run.",
})
def run_skullstrip(c, subjects=None, tools=None, retry_failed=False, smoke=False):
    """
    Execute output_data/plan.json: one container run per (T1w × tool).

    Each run writes its mask to output_data/derivatives/<tool>/, its container
    log to logs/ and its record (status, duration, error) to runs/. The record
    is the "already done" marker — failed runs included, so a slow run that
    ran out of memory is not relaunched every time; use --retry-failed.
    Never fetches anything: it reads the plan, written by run-check.
    """
    import json

    from invoke.exceptions import Exit

    from analysis.skullstrip import run_plan

    plan_file = Path(c.config.get("output_data_dir")) / "plan.json"
    if not plan_file.is_file():
        raise Exit("❌ No plan yet: run `invoke run-check` first.")
    plan = json.loads(plan_file.read_text())
    if not plan["ready"]:
        raise Exit("❌ The plan is not ready: fix what `invoke run-check` reports.")
    run_plan(plan, subjects=[label.removeprefix("sub-") for label in split_list(subjects) or []],
             tools=split_list(tools), retry_failed=retry_failed, smoke=smoke)


@task
def run_metrics(c):
    """
    Write output_data/metrics.csv: per run, mask volume (mL), Dice against the
    consensus of the tools that succeeded on the same T1w, duration, status.

    Always re-runs, like run-check: it takes seconds, and the consensus — hence
    every Dice — changes whenever a run is added, so a cached table would
    silently go stale.
    """
    from analysis.metrics import compute_metrics

    output_dir = Path(c.config.get("output_data_dir"))
    metrics = compute_metrics(output_dir / "runs")
    metrics.to_csv(output_dir / "metrics.csv", index=False)
    print(f"📊 {len(metrics)} runs → {output_dir / 'metrics.csv'}")


@task
def run_report(c):
    """
    Write output_data/report.html: one row per T1w, one column per tool, each
    cell showing the mask's outline on the T1w, its metrics, and OK / Fail /
    Doubtful buttons with a comment box (notes exported as CSV by the page).

    Each run's pictures (a thumbnail and a full-size version, as JPEG) are
    cached in output_data/figures/<tool>/ — drawing takes seconds — while the
    HTML itself is rebuilt every time, since
    it reflects metrics.csv, which always changes. Self-contained (images
    embedded), so the file can be shared alone.
    """
    from invoke.exceptions import Exit

    from analysis.report import build_report

    output_dir = Path(c.config.get("output_data_dir"))
    if not (output_dir / "metrics.csv").is_file():
        raise Exit("❌ No metrics yet: run `invoke run-metrics` first.")
    build_report(
        runs_dir=output_dir / "runs",
        metrics_csv=output_dir / "metrics.csv",
        figures_dir=output_dir / "figures",
        output_html=output_dir / "report.html",
        plausible_volume_ml=c.config.get("report")["plausible_volume_ml"],
    )
    print(f"📄 Report: {(output_dir / 'report.html').resolve()}")


# --------------------------------------------------------------------------- #
# Pipeline
# --------------------------------------------------------------------------- #
@task(help={
    "force": "Delete every computed output first, then run from scratch.",
})
def run(c, force=False):
    """
    Full pipeline: check → skullstrip → metrics → report.

    Steps are called directly rather than through `pre=`, so that flags like
    --force reach them: a `pre=` chain runs before this body, which would be
    too late.

    Every step caches by checking whether its output already exists, so a
    repeated `run` does nothing. That is deliberate — but it also means an
    edited script or notebook will NOT re-run on its own. `--force` is the
    sledgehammer: clean everything, then start over. To redo one step, call its
    `clean-{name}` task and run again. `run-check` is the one deliberate
    exception, and so is `run-metrics`: both always re-run (see their docstrings).
    """
    from airoh.provenance import record_run

    if force:
        print("💥 --force: removing every computed output before running")
        clean(c)
    run_check(c)
    run_skullstrip(c)
    run_metrics(c)
    run_report(c)
    record_run(c, tasks="run-check,run-skullstrip,run-metrics,run-report")
    print("all analyses completed")


@task
def run_smoke(c):
    """
    Smoke test: a minimal end-to-end pass over the whole pipeline.

    Calls the steps directly (rather than via `pre=`) so each can be given a
    reduced workload. The point is to exercise the plumbing quickly, not to
    produce real results: one T1w × SynthStrip.
    """
    fetch(c)
    run_check(c, tools="synthstrip", smoke=True)
    run_skullstrip(c, smoke=True)
    run_metrics(c)
    run_report(c)
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
@task
def clean_check(c):
    """
    Remove output_data/plan.json.
    """
    from airoh.utils import clean_folder
    clean_folder(c, "output_data_dir", "plan.json")


@task(help={"tools": "Comma-separated tools to clean (default: all)."})
def clean_skullstrip(c, tools=None):
    """
    Remove the outputs of run-skullstrip: derivatives/, runs/, logs/, work/,
    and the report pictures of those masks in figures/ (a picture is only
    valid for the mask it was drawn from).

    With --tools, only those tools' folders go, so their runs (failed ones
    included) are redone on the next `invoke run`.
    """
    import shutil

    output_dir = Path(c.config.get("output_data_dir"))
    for folder in ("derivatives", "runs", "logs", "work", "figures"):
        targets = [output_dir / folder / tool for tool in split_list(tools)] if tools \
            else [output_dir / folder]
        for target in targets:
            if target.is_dir():
                shutil.rmtree(target)
                print(f"🧹 Removed: {target}")


@task
def clean(c):
    """
    Remove all computed outputs.

    The steps are called in the body rather than declared as `pre=`, because a
    `pre=` chain only fires when invoke runs the task from the command line.
    Calling `clean(c)` from Python — which is what `run --force` does — would
    otherwise execute an empty function and silently delete nothing.
    """
    clean_check(c)
    clean_skullstrip(c)
    clean_metrics(c)
    clean_report(c)


@task
def clean_metrics(c):
    """
    Remove output_data/metrics.csv.
    """
    from airoh.utils import clean_folder
    clean_folder(c, "output_data_dir", "metrics.csv")


@task
def clean_report(c):
    """
    Remove output_data/report.html and every cached picture (figures/).
    """
    import shutil

    from airoh.utils import clean_folder

    clean_folder(c, "output_data_dir", "report.html")
    figures_dir = Path(c.config.get("output_data_dir")) / "figures"
    if figures_dir.is_dir():
        shutil.rmtree(figures_dir)
        print(f"🧹 Removed: {figures_dir}")


def unlink_asset(c, name):
    """
    Remove a source asset's link (or copy) in source_data/. For a symlink, only
    the link goes: the dataset or images it points at are untouched.
    """
    import shutil

    path = Path(c.config.get("files")[name]["output_file"])
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)
    else:
        print(f"🫧 Skipping: {path} does not exist.")
        return
    print(f"🧹 Removed: {path}")


@task
def clean_bids(c):
    """
    Remove source_data/bids (the link, not the dataset it points to).

    Not called by `clean` or `run --force` — those only touch output_data/.
    Use this before `invoke fetch-bids --source` to point at another dataset:
    fetch never overwrites an existing link.
    """
    unlink_asset(c, "bids")


@task
def clean_containers(c):
    """
    Remove source_data/containers (the link, not the images it points to).
    """
    unlink_asset(c, "containers")


@task
def clean_ants_template(c):
    """
    Remove the downloaded ANTs template (tools/ants/Oasis.zip and template/).
    """
    import shutil

    zip_file = Path(c.config.get("files")["ants_template"]["output_file"])
    zip_file.unlink(missing_ok=True)
    shutil.rmtree(zip_file.parent / "template", ignore_errors=True)
    print(f"🧹 Removed: {zip_file} and {zip_file.parent / 'template'}")


@task
def clean_source(c):
    """
    Remove all source data assets. Body calls each clean-{name} task.
    """
    clean_bids(c)
    clean_containers(c)
    clean_ants_template(c)
