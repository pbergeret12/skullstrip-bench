"""
Where everything goes. The one place that decides it, so that what the user
sees stays exactly this:

    <output>/report.html            the report
    <output>/figures/               its pictures (thumbnail + full size per run)
    <output>/metrics.csv            volume, Dice, duration, status per run

    <workdir>/logs/<tool>/<stem>.log   what the container printed (command first)
    <workdir>/logs/<tool>/<stem>.err   its errors, and why the run failed if it did
    <workdir>/logs/slurm_*.log|.err    the cluster jobs' own logs
    <workdir>/skullstrip_bench.sbatch  with --scheduler slurm: the job to submit
    <workdir>/jobs.txt                 with --scheduler slurm: one participant per line

`<output>` is --output; `<workdir>` is the working directory the command is
run from (or --workdir). Everything the tool needs for itself (the plan, the
"already done" records, the masks, the per-participant parts of the
incremental report, provenance) lives in the hidden folder
`<output>/.skullstrip-bench/`. Raw tool outputs go to a scratch folder there
and are deleted after each run.
"""
from pathlib import Path

STATE_FOLDER = ".skullstrip-bench"


def report_path(output_dir, *parts):
    return Path(output_dir, *parts)


def logs_path(workdir, *parts):
    return Path(workdir, "logs", *parts)


def state_path(output_dir, *parts):
    return Path(output_dir, STATE_FOLDER, *parts)
