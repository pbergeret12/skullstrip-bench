"""
Where everything goes inside an output folder (--output). The one place that
decides it, so the visible output stays exactly:

    report/report.html          the report
    report/figures/             its pictures (thumbnail + full size per run)
    report/metrics.csv          volume, Dice, duration, status per run
    logs/<tool>/<stem>.log      what the container printed (command first)
    logs/<tool>/<stem>.err      its errors, and why the run failed if it did
    logs/slurm/                 the cluster jobs' .log and .err
    slurm/                      with --scheduler slurm only: the generated
                                sbatch scripts and jobs.txt, for the user to
                                edit (--account, --array) and submit

Everything the tool needs for itself (the plan, the "already done" records,
the masks, the per-participant parts of the incremental report, provenance)
lives in the hidden folder `.skullstrip-bench/`.
Raw tool outputs go to a work folder there and are deleted after each run.
"""
from pathlib import Path

STATE_FOLDER = ".skullstrip-bench"


def report_path(output_dir, *parts):
    return Path(output_dir, "report", *parts)


def logs_path(output_dir, *parts):
    return Path(output_dir, "logs", *parts)


def slurm_path(output_dir, *parts):
    return Path(output_dir, "slurm", *parts)


def state_path(output_dir, *parts):
    return Path(output_dir, STATE_FOLDER, *parts)
