"""
`run --scheduler slurm`: write ready-to-edit Slurm scripts instead of running.

Nothing is submitted. In the output's internal state folder
(`.skullstrip-bench/slurm/`) this writes:
- `jobs.txt` — one participant per line (`sub-XX`); array task N handles line N;
- `skullstrip_array.sh` — the job array: one task = one participant, every
  selected tool run on all of that participant's T1w images, then that
  participant is added to the metrics and the report (incremental);
- `skullstrip_report.sh` — a final rebuild of metrics and report, plus the
  provenance record, once the array has ended;
- `submit.sh` — submits both, chaining the report after the array.

The account and the array range (how many participants to launch) are taken
from --slurm-account / --slurm-array, or left for the user to edit. Resources
come from the tools' YAML (`cpus`, `mem_gb`, `minutes`), or from durations
already measured with Apptainer.

When the tool itself runs from its container (skullstrip-bench.sif), the jobs
call that same image through `apptainer exec`, with every input and output
folder bound at the same path inside, so the plan's paths stay valid.
"""
import json
import math
import os
import shlex
from collections import Counter

from analysis.layout import logs_path, state_path
from datetime import date
from pathlib import Path

ACCOUNT_PLACEHOLDER = "def-CHANGEME"
TIME_MARGIN = 1.5                   # walltime = estimate × margin + overhead
OVERHEAD_MINUTES = 10               # image start-up, report pictures, copies
TIME_STEP_MINUTES = 15              # walltimes are rounded up to this
REPORT_MINUTES_PER_RUN = 0.05       # embedding pictures and metrics, per run
REPORT_BASE_MINUTES = 30


def write_slurm_files(plan, repo_dir, invoke_bin, command_line, account=None, array=None):
    """Write the Slurm files for `plan`, return the folder they are in."""
    output_dir = Path(plan["output_dir"]).resolve()
    slurm_dir = state_path(output_dir, "slurm")
    slurm_dir.mkdir(parents=True, exist_ok=True)
    logs_path(output_dir, "slurm").mkdir(parents=True, exist_ok=True)
    jobs_file = slurm_dir / "jobs.txt"
    jobs_file.write_text("\n".join(plan["subjects"]) + "\n")

    resources = participant_resources(plan)
    context = {
        **tool_invocation(plan, repo_dir, invoke_bin),
        "account": account or ACCOUNT_PLACEHOLDER,
        "array": array or f"1-{len(plan['subjects'])}",
        "output": shlex.quote(str(Path(plan["output_dir"]).resolve())),
        "logs": logs_path(output_dir, "slurm"),
        "jobs": shlex.quote(str(jobs_file)),
        "header": header(command_line),
    }
    files = {
        "skullstrip_array.sh": array_script(len(plan["subjects"]), resources, context),
        "skullstrip_report.sh": report_script(len(plan["runs"]), context),
        "submit.sh": SUBMIT_SCRIPT,
    }
    for name, text in files.items():
        (slurm_dir / name).write_text(text)
        (slurm_dir / name).chmod(0o755)
    return slurm_dir, resources


def tool_invocation(plan, repo_dir, invoke_bin):
    """
    How a job calls the tool: `setup` lines, then the `invoke` command prefix.

    From the tool's container, the job runs that same .sif with every folder
    of the plan (and the node's local disk) bound at the same path. Otherwise
    it runs this checkout's invoke, from the checkout.
    """
    if os.environ.get("SKULLSTRIP_BENCH_IN_CONTAINER"):
        image = os.environ.get("APPTAINER_CONTAINER", "/path/to/skullstrip-bench.sif")
        # The tools' requirements ship inside the image: nothing to bind.
        folders = [plan[key] for key in ("bids_dir", "containers_dir", "output_dir")]
        binds = ",".join(shlex.quote(folder) for folder in folders) + ',"$SLURM_TMPDIR"'
        return {"setup": "",
                "invoke": f"apptainer exec --bind {binds} {shlex.quote(image)} skullstrip-bench"}
    return {"setup": f"cd {shlex.quote(str(Path(repo_dir).resolve()))}\n",
            "invoke": shlex.quote(str(invoke_bin))}


def participant_resources(plan):
    """
    Resources for one array task (one participant, every tool in sequence).

    Cores and memory: the largest of the tools, since they run one after the
    other. Time: the sum of the tools' durations for the participant with the
    most T1w images, with a margin.
    """
    tools = plan["tools"]
    minutes_per_run, sources = {}, {}
    for name, tool in tools.items():
        measured = measured_minutes(state_path(plan["output_dir"], "runs", name))
        minutes_per_run[name] = measured or tool["minutes"]
        sources[name] = "measured" if measured else "estimated"
    t1w_images = {(run["subject"], run["stem"]) for run in plan["runs"]}
    most_t1w = max(Counter(subject for subject, _ in t1w_images).values())
    expected = most_t1w * sum(minutes_per_run.values())
    walltime = round_up(expected * TIME_MARGIN + OVERHEAD_MINUTES, TIME_STEP_MINUTES)
    return {
        "cpus": max(tool["cpus"] for tool in tools.values()),
        "mem_gb": max(tool["mem_gb"] for tool in tools.values()),
        "minutes": walltime,
        "expected_minutes": round(expected, 1),
        "per_tool": {name: (round(minutes_per_run[name], 1), sources[name]) for name in tools},
    }


def measured_minutes(tool_runs_dir):
    """The longest successful Apptainer run of a tool so far, in minutes (or None)."""
    durations = []
    for record_file in Path(tool_runs_dir).glob("*.json"):
        record = json.loads(record_file.read_text())
        if record["status"] == "ok" and record["engine"] == "apptainer":
            durations.append(record["duration_s"] / 60)
    return max(durations) if durations else None


def round_up(minutes, step):
    return max(step, math.ceil(minutes / step) * step)


def hours_minutes(minutes):
    """Slurm's `HH:MM:00`."""
    return f"{int(minutes) // 60:02d}:{int(minutes) % 60:02d}:00"


def header(command_line):
    return (f"# Generated by skullstrip-bench on {date.today().isoformat()} with:\n"
            f"#   {command_line}\n")


def array_script(n_subjects, resources, context):
    """The job array: task N processes the participant on line N of jobs.txt."""
    per_tool = "\n".join(f"#   {name}: {minutes} min per T1w ({source})"
                         for name, (minutes, source) in resources["per_tool"].items())
    return f"""#!/bin/bash
# skullstrip-bench: one array task = one participant (one line of jobs.txt),
# every selected tool run on all of that participant's T1w images.
{context['header']}#
# BEFORE SUBMITTING
#   1. --account must be your allocation (e.g. def-yourpi or rrg-yourpi), here and
#      in skullstrip_report.sh (set it at generation with --slurm-account).
#   2. Choose which participants to launch with --array (line numbers of jobs.txt):
#        {f"--array=1-{n_subjects}":<20} every participant ({n_subjects} lines in jobs.txt)
#        {f"--array=1-{min(20, n_subjects)}":<20} a pilot on the first {min(20, n_subjects)}
#        {f"--array=1-{n_subjects}%50":<20} every participant, at most 50 running at once
#   3. Submit with ./submit.sh, which also schedules the report after the array.
#
# Resources are for ONE participant (the tools run one after the other):
{per_tool}
#   expected {resources['expected_minutes']} min, walltime with margin: {resources['minutes']} min
# After a pilot, re-run the same command: measured durations replace estimates.
#SBATCH --account={context['account']}
#SBATCH --job-name=skullstrip-bench
#SBATCH --array={context['array']}
#SBATCH --cpus-per-task={resources['cpus']}
#SBATCH --mem={resources['mem_gb']}G
#SBATCH --time={hours_minutes(resources['minutes'])}
#SBATCH --output={context['logs']}/array_%A_%a.log
#SBATCH --error={context['logs']}/array_%A_%a.err

set -euo pipefail
module load apptainer

SUBJECT=$(sed -n "${{SLURM_ARRAY_TASK_ID}}p" {context['jobs']})
if [ -z "$SUBJECT" ]; then
    echo "jobs.txt has no line ${{SLURM_ARRAY_TASK_ID}}: check --array" >&2
    exit 1
fi
echo "Participant $SUBJECT (array task ${{SLURM_ARRAY_TASK_ID}})"

{context['setup']}# Work on the node's local disk; only masks, logs and records reach --output.
{context['invoke']} run-skullstrip --output {context['output']} --subjects "$SUBJECT" \\
    --threads "$SLURM_CPUS_PER_TASK" --work-root "$SLURM_TMPDIR/work"
# Add this participant to the report: its pictures, metrics and rows, then
# rebuild report/report.html (open it any time; reload to see new participants).
{context['invoke']} run-update --output {context['output']} --subjects "$SUBJECT"
"""


def report_script(n_runs, context):
    """The final job: metrics (consensus needs every tool) and the HTML report."""
    minutes = round_up(REPORT_BASE_MINUTES + n_runs * REPORT_MINUTES_PER_RUN,
                       TIME_STEP_MINUTES)
    return f"""#!/bin/bash
# skullstrip-bench: metrics and HTML report, once every array task has ended.
{context['header']}#
# --account must be your allocation (set it at generation with --slurm-account).
#SBATCH --account={context['account']}
#SBATCH --job-name=skullstrip-bench-report
#SBATCH --cpus-per-task=1
#SBATCH --mem=8G
#SBATCH --time={hours_minutes(minutes)}
#SBATCH --output={context['logs']}/report_%j.log
#SBATCH --error={context['logs']}/report_%j.err

set -euo pipefail
module load apptainer
{context['setup']}{context['invoke']} run-aggregate --output {context['output']}
"""


SUBMIT_SCRIPT = f"""#!/bin/bash
# Submit the array, then the report job. The report waits for every array task
# to end, successfully or not: failed runs are part of the report.
set -euo pipefail
cd "$(dirname "$0")"
if grep -q "{ACCOUNT_PLACEHOLDER}" skullstrip_array.sh skullstrip_report.sh; then
    echo "Edit --account in skullstrip_array.sh and skullstrip_report.sh first." >&2
    exit 1
fi
array_job=$(sbatch --parsable skullstrip_array.sh)
echo "Array job $array_job submitted"
report_job=$(sbatch --parsable --dependency=afterany:${{array_job%%;*}} skullstrip_report.sh)
echo "Report job $report_job will start once the array has ended"
"""
