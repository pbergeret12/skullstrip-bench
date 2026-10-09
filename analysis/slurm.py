"""
`run --scheduler slurm`: write one sbatch script instead of running.

Nothing is submitted. In the working directory (where the command is run,
or --workdir) this writes:
- `jobs.txt`: one participant per line (`sub-XX`);
- `skullstrip_bench.sbatch`: the job array, one task per participant (task N
  takes line N of jobs.txt), running every selected tool on all of that
  participant's T1w images, then adding the participant to the report;
and the jobs write their `.log` and `.err` to the working directory's `logs/`.

There is no separate report job: the report is incremental, every task
updates it, so `sbatch skullstrip_bench.sbatch` is the only command. The user
edits `--account` (left as def-CHANGEME) and, to run fewer than all
participants, `--array` (every line of jobs.txt by default). Resources come
from the tools' YAML (`cpus`, `mem_gb`, `minutes`), or from durations already
measured with Apptainer.

When the tool itself runs from its container (skullstrip-bench.sif), the job
calls that same image through `apptainer exec`, with every folder it reads or
writes bound at the same path inside, so the plan's paths stay valid.
"""
import json
import math
import os
import shlex
from collections import Counter
from datetime import date
from pathlib import Path

from analysis.layout import state_path

ACCOUNT_PLACEHOLDER = "def-CHANGEME"
SBATCH_FILE = "skullstrip_bench.sbatch"
JOBS_FILE = "jobs.txt"
TIME_MARGIN = 1.5                   # walltime = estimate × margin + overhead
OVERHEAD_MINUTES = 10               # image start-up, report pictures, copies
TIME_STEP_MINUTES = 15              # walltimes are rounded up to this


def write_slurm_files(plan, repo_dir, invoke_bin, command_line):
    """Write jobs.txt and the sbatch script in the plan's working directory."""
    workdir = Path(plan["workdir"])
    (workdir / "logs").mkdir(parents=True, exist_ok=True)
    jobs_file = workdir / JOBS_FILE
    jobs_file.write_text("\n".join(plan["subjects"]) + "\n")

    resources = participant_resources(plan)
    context = {
        **tool_invocation(plan, repo_dir, invoke_bin),
        "output": shlex.quote(plan["output_dir"]),
        "workdir": shlex.quote(str(workdir)),
        "logs": workdir / "logs",
        "jobs": shlex.quote(str(jobs_file)),
        "header": header(command_line),
    }
    sbatch_file = workdir / SBATCH_FILE
    sbatch_file.write_text(sbatch_script(len(plan["subjects"]), resources, context))
    return sbatch_file, resources


def tool_invocation(plan, repo_dir, invoke_bin):
    """
    How a job calls the tool: `setup` lines, then the `invoke` command prefix.

    From the tool's container, the job runs that same .sif with every folder
    it uses (and the node's local disk) bound at the same path. Otherwise it
    runs this checkout's invoke, from the checkout.
    """
    if os.environ.get("SKULLSTRIP_BENCH_IN_CONTAINER"):
        image = os.environ.get("APPTAINER_CONTAINER", "/path/to/skullstrip-bench.sif")
        # The tools' requirements ship inside the image: nothing to bind.
        folders = [plan[key] for key in ("bids_dir", "containers_dir", "output_dir", "workdir")]
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


def sbatch_script(n_subjects, resources, context):
    """The job array: task N processes the participant on line N of jobs.txt."""
    per_tool = "\n".join(f"#   {name}: {minutes} min per T1w ({source})"
                         for name, (minutes, source) in resources["per_tool"].items())
    return f"""#!/bin/bash
# skullstrip-bench: one array task = one participant (one line of jobs.txt),
# every selected tool run on all of that participant's T1w images, after
# which the participant is added to the report in {context['output']}.
{context['header']}#
# BEFORE SUBMITTING
#   1. Replace {ACCOUNT_PLACEHOLDER} below with your allocation (e.g. def-yourpi).
#   2. --array picks the participants (line numbers of jobs.txt):
#        {f"--array=1-{n_subjects}":<20} every participant ({n_subjects} lines in jobs.txt)
#        {f"--array=1-{min(20, n_subjects)}":<20} a pilot on the first {min(20, n_subjects)}
#        {f"--array=1-{n_subjects}%50":<20} every participant, at most 50 running at once
#   3. Submit:  sbatch {SBATCH_FILE}
#
# Resources are for ONE participant (the tools run one after the other):
{per_tool}
#   expected {resources['expected_minutes']} min, walltime with margin: {resources['minutes']} min
# After a pilot, generate this file again: measured durations replace estimates.
#SBATCH --account={ACCOUNT_PLACEHOLDER}
#SBATCH --job-name=skullstrip-bench
#SBATCH --array=1-{n_subjects}
#SBATCH --cpus-per-task={resources['cpus']}
#SBATCH --mem={resources['mem_gb']}G
#SBATCH --time={hours_minutes(resources['minutes'])}
#SBATCH --output={context['logs']}/slurm_%A_%a.log
#SBATCH --error={context['logs']}/slurm_%A_%a.err

set -euo pipefail
module load apptainer

SUBJECT=$(sed -n "${{SLURM_ARRAY_TASK_ID}}p" {context['jobs']})
if [ -z "$SUBJECT" ]; then
    echo "jobs.txt has no line ${{SLURM_ARRAY_TASK_ID}}: check --array" >&2
    exit 1
fi
echo "Participant $SUBJECT (array task ${{SLURM_ARRAY_TASK_ID}})"

{context['setup']}# Work on the node's local disk; the tools' logs go to {context['workdir']}/logs/.
{context['invoke']} run-skullstrip --output {context['output']} --subjects "$SUBJECT" \\
    --threads "$SLURM_CPUS_PER_TASK" --work-root "$SLURM_TMPDIR/work"
# Add this participant to the report (open it any time; reload to see new ones).
{context['invoke']} run-update --output {context['output']} --subjects "$SUBJECT"
"""
