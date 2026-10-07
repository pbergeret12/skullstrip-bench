# Skullstrip Bench

_why don't you have a cup of relaxing jasmine tea?_

Skullstrip Bench runs several containerized skull-stripping tools (SynthStrip, FSL BET, SynthSeg, ANTs) on every T1w image of a BIDS dataset, then builds a self-contained HTML report in which you rate each brain mask. There is no ground truth: the final call is yours, and the metrics (mask volume, Dice against the consensus of all tools, runtime) are only there to guide the eye.

Two goals drive the design:
- **No setup and no downloads, ever.** The tool runs the container images you already have, reads your files where they are, and never touches the network. That is what lets it run on cluster compute nodes without internet access, such as the Digital Research Alliance of Canada's.
- **Processing code that stays easy to read.**

It runs **locally** (Docker or Apptainer), or **on a Slurm cluster**: in that mode it writes ready-to-edit job scripts, one array task per participant.

Built on the [`invoke`](https://www.pyinvoke.org/) task runner and [`airoh`](https://pypi.org/project/airoh/) (from the `airoh-mini` template).

⚠️ **Status**: built during BrainHack School. All four tools work end to end under Docker. The Slurm mode is written and tested locally, but has not run on a real cluster yet, and Apptainer runs are still untested.

---

## ✨ TL;DR

```bash
uv sync
uv run invoke run --bids /path/to/bids --containers /path/to/images \
                  --requirements /path/to/container_requirements --output /path/to/results
# → /path/to/results/report.html
```

On a cluster, add `--scheduler slurm`, then edit and submit the generated scripts (see [Running on a Slurm cluster](#-running-on-a-slurm-cluster)).

---

## 🚀 Quick Start

### Step 1: Install

```bash
uv sync
```

This creates a `.venv` with the runtime dependencies plus the dev tools (`flake8`, `pytest`). You also need a container engine: **Docker** (daemon running) or **Apptainer**. Apptainer is used if available, otherwise Docker; force one with `--engine docker`.

### Step 2: Gather three folders

| Flag | What it points to |
| ---- | ----------------- |
| `--bids` | Your **BIDS dataset**. Only `dataset_description.json` and the T1w images in each subject's anat folder (sessions allowed) are read. |
| `--containers` | A folder holding **only container images**: Docker archives `<name>.tar` (from `docker save`) and/or Apptainer `<name>.sif`. File names must match the table in [Compatible containers](#-compatible-containers). |
| `--requirements` | Only for tools that need extra files (ANTs, today): **one subfolder per tool** holding its atlases, templates or configs, e.g. `container_requirements/ants/`. |
| `--output` | Where every result goes (default: `output_data/` in this repository). Use one output folder per dataset. |

Nothing is copied or linked: the folders are read in place. To avoid retyping the paths on one machine, set defaults under `inputs:` in `invoke.yaml`.

### Step 3: Check, then run

```bash
uv run invoke run-check --bids … --containers … --requirements … --output …
```

`run-check` launches nothing and takes seconds, whatever the dataset size. It checks:
- **the dataset, shallowly**: `dataset_description.json`, the `sub-*` folders, and T1w files where BIDS puts them. It never opens an image: a broken T1w simply fails its own run.
- **the tools**: without `--tools`, every image in `--containers` that has a config in `tools/` and whose required files are in `--requirements` is used. Other images are reported as *not compatible* and skipped. With `--tools synthstrip,fsl-bet`, only those.
- **the engine** and **the output folder**.

It then prints a ✔/✘ summary and writes the run plan to `<output>/plan.json`. Restrict it further with `--subjects 10159,10171`.

```bash
uv run invoke run --bids … --containers … --requirements … --output …   # check → runs → report
uv run invoke run … --force                                            # clean, then run from scratch
```

Each (T1w × tool) run writes a BIDS-derivative mask, its container log, and a record of its status and duration. A run that fails is recorded and the next one starts. A run fails when:
- the tool itself errors;
- it runs out of memory;
- it runs longer than the tool's `timeout_min`;
- its mask is missing, not binary, or off the T1w grid.

Every step skips work whose output already exists, so `invoke run` is cheap to repeat. Failed runs count as done too, so a slow tool that crashed is not relaunched every time. To redo runs:
- retry the failed ones with `uv run invoke run-skullstrip --output … --retry-failed`;
- redo one tool with `uv run invoke clean-skullstrip --output … --tools fsl-bet`.

The flip side: editing a script does **not** re-run anything. Use `--force`, or a `clean-{name}` task, to rebuild.

### Step 4: Judge the masks

Open **`<output>/report.html`** in a browser. It has one row per T1w and one column per tool. Each cell shows the T1w with the mask's outline in red, in axial, coronal and sagittal views, with the same slices for every tool.

Click a picture to open its high-resolution version:
- zoom with the mouse wheel and drag to move;
- use the arrow keys to switch to another tool (← →) or T1w (↑ ↓) **at the same zoom and position**.

Under each picture:
- the mask volume, highlighted outside the plausible range set in `invoke.yaml` (`report: plausible_volume_ml`, 1100–1600 mL by default);
- the Dice against the consensus of the tools;
- the runtime.

A failed run shows its error instead. Rate each mask **OK / Fail / Doubtful**, add a comment, then use **Export notes (CSV)**. Notes are kept in your browser between reloads, but the CSV export is your real record.

The file is self-contained (images embedded), so you can send it as is. It shows participants' brains, though, so share it only where the dataset's rules allow.

### Step 5: Smoke test and consistency checks

```bash
uv run invoke run-smoke --bids … --containers …   # 1 T1w × SynthStrip, end to end
uv run invoke verify                              # code, config, data and docs still agree
uv run pytest                                     # unit tests
uv run flake8                                     # linter
```

---

## 🖥️ Running on a Slurm cluster

On the cluster, nothing is computed at generation time: the tool writes job scripts that you read, edit and submit.

1. **Copy the images once** (the `.tar` files, or `.sif` you already built) and the requirements folder to the cluster. Compute nodes have no internet, and the tool never downloads anything.
2. **Build the `.sif` files once**, on a login node or in an interactive job:
   ```bash
   module load apptainer
   uv run invoke prepare-images --containers /path/to/images
   ```
   Each `<name>.sif` is built from its `<name>.tar`, next to it. Array tasks only read them, so they never race to build the same image.
3. **Generate the scripts:**
   ```bash
   uv run invoke run --scheduler slurm --bids … --containers … --requirements … --output $SCRATCH/results
   ```
   This writes to `<output>/slurm/`:

   | File | Content |
   | ---- | ------- |
   | `jobs.txt` | One participant per line (`sub-XX`). Array task N processes line N. |
   | `skullstrip_array.sh` | The job array. One task = one participant: every selected tool on all of that participant's T1w images, working on the node's local disk (`$SLURM_TMPDIR`), with the threads Slurm granted, then that participant's report pictures. |
   | `skullstrip_report.sh` | Metrics, report and provenance, once the array has ended. |
   | `submit.sh` | Submits the array, then the report job with `--dependency=afterany`. It refuses to submit until `--account` is edited. |

   The array's resources are pre-filled for one participant:
   - **CPUs and memory**: the largest of the selected tools, since they run one after the other.
   - **Time**: the sum of the tools' durations × 1.5 + 10 min. Durations come from each tool's YAML, or from durations already measured with Apptainer in that output folder.
4. **Edit, then submit:**
   - replace `def-CHANGEME` with your allocation (e.g. `def-yourpi`) in both `.sh` files;
   - choose how many participants to launch with `#SBATCH --array`: `1-20` for a pilot on the first 20, `1-N` for all, `1-N%50` for all with at most 50 at once;
   - then run `<output>/slurm/submit.sh`.
5. **After a pilot**, re-run the same `--scheduler slurm` command: the measured durations replace the estimates, so the walltime fits your cluster. Check the real memory peak with `seff <jobid>`.

---

## 📦 Compatible containers

A container is compatible when `tools/` has a config for it. For it to run, its image must sit in `--containers` under the file name below, and its required files (if any) must be in `--requirements`. Prepare each image once, on a machine with internet:

```bash
docker pull <image> && docker save -o <file name>.tar <image>
```

| Tool | Image | File name in `--containers` | Required files in `--requirements` | Output | Runtime per T1w (Mac, amd64 emulation) | Cluster resources (YAML) |
| ---- | ----- | --------------------------- | --------------------------------- | ------ | -------------------------------------- | ------------------------ |
| `synthstrip` | `freesurfer/synthstrip:1.8` | `synthstrip_1.8.tar` / `.sif` | — | brain mask (CSF included) | ≈ 17 s | 4 CPUs, 8 GB |
| `fsl-bet` | `gamorosino/fsl:6.0.7.22` | `fsl_6.0.7.22.tar` / `.sif` | — | brain mask (`bet -m -R`) | ≈ 8 s | 1 CPU, 2 GB |
| `synthseg` | `cookpa/synthseg:conda-0.2` | `synthseg_conda-0.2.tar` / `.sif` | — | segmentation → mask: every label > 0 (CSF included), resampled onto the T1w grid | 3–5 min | 8 CPUs, 16 GB |
| `ants` | `antsx/ants:latest` | `ants_latest.tar` / `.sif` | `ants/T_template0.nii.gz`, `ants/T_template0_BrainCerebellumProbabilityMask.nii.gz`, `ants/T_template0_BrainCerebellumRegistrationMask.nii.gz` | `antsBrainExtraction.sh` mask | ≈ 6.5 min | 8 CPUs, 8 GB |

Notes:
- **ANTs template**: the three files come from the OASIS template in the ANTs templates on figshare ([doi:10.6084/m9.figshare.915436](https://doi.org/10.6084/m9.figshare.915436), file `Oasis.zip`, folder `MICCAI2012-Multi-Atlas-Challenge-Data/`). Download it once on a machine with internet, and copy only those three files into `container_requirements/ants/`.
- **SynthSeg memory**: under Docker on a Mac, give the Docker VM at least 12 GB. With 8 GB, the VM crashed.
- **Free disk space**: also check it before long Docker runs. A full disk is what crashed Docker during development.
- **The runtimes** were measured under amd64 emulation on an Apple Silicon Mac. Expect faster runs natively.

### Adding a tool

One YAML in `tools/` plus one image in the containers folder (and its files in the requirements folder, if any):

```yaml
# tools/mytool.yaml
name: mytool                        # must match the file name
image: someone/mytool:2.0           # Docker reference
container: mytool_2.0               # <containers>/mytool_2.0.tar or .sif
command: mytool --in {input} --mask {mask} --threads {threads}
# mask_output: "{output_prefix}_mask.nii.gz"   # if the tool picks its own mask name
# postprocess: labels_to_mask                    # if the tool outputs a segmentation
# requires: [atlas.nii.gz]                       # files in <requirements>/mytool/
timeout_min: 30                     # stop a run stuck for 30 minutes
cpus: 4                             # cluster resources for one run
mem_gb: 8
minutes: 5                          # expected duration on a cluster node
```

The tool sees paths inside the container through these placeholders:

| Placeholder | Meaning |
| ----------- | ------- |
| `{input}` | the T1w |
| `{mask}` | where to write the mask |
| `{output_prefix}` | a prefix for tools that name their own outputs |
| `{requirements}` | its requirements subfolder, read-only |
| `{threads}` | the cores it may use |

The launcher also sets `OMP_NUM_THREADS` and `ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS`, so a tool never grabs every core of a shared node. Do not write `${VAR}` in a command, because braces are placeholders here; `$VAR` works.

---

## 🧰 Task Overview

| Task               | Description |
| ------------------ | ----------- |
| `run`              | Full pipeline: check → runs → figures → metrics → report. `--scheduler slurm` writes job scripts instead of running; `--force` cleans first |
| `run-check`        | Checks dataset (shallow), tools, images, requirements, engine and output without running anything; writes `<output>/plan.json` and `MANIFEST.json`; always re-runs |
| `run-skullstrip`   | Executes the plan, one container run per (T1w × tool); `--subjects`, `--tools`, `--retry-failed`, `--threads`, `--work-root` |
| `run-figures`      | Draws the report pictures of finished runs (cached); a cluster array task draws its own participant's |
| `run-metrics`      | Writes `<output>/metrics.csv`: volume, Dice against the consensus, duration and status per run; always re-runs |
| `run-report`       | Writes `<output>/report.html`: masks drawn on the T1w, metrics, rating buttons and CSV export; the HTML is always rebuilt |
| `run-aggregate`    | Metrics, report and provenance record: the end of `run`, and the cluster report job |
| `run-smoke`        | Fast end-to-end pass: 1 T1w × SynthStrip, run locally |
| `prepare-images`   | Builds each tool's Apptainer `.sif` from its `.tar`, once (run on a login node before `--scheduler slurm`) |
| `verify`           | Checks that code, config, data and docs still agree |
| `clean`            | Removes all computed outputs of an output folder |
| `clean-check`      | Removes `plan.json` and `MANIFEST.json` |
| `clean-skullstrip` | Removes masks, run records, logs, work folders and their report pictures; `--tools` limits it to some tools |
| `clean-metrics`    | Removes `metrics.csv` |
| `clean-report`     | Removes the report and its cached pictures |
| `clean-slurm`      | Removes the generated Slurm files and job logs |

Every task that reads or writes results takes `--output` (default: `output_data/`). Use `uv run invoke --list` or `uv run invoke --help <task>` for details.

---

## 📁 Folder Structure

| Folder / File  | Description |
| -------------- | ----------- |
| `analysis/`    | Processing code called by the tasks: BIDS parsing, mask validation, tool configs, the container launcher (the only engine-aware module), the checks, the Slurm script writer, metrics and report |
| `tools/`       | One YAML per skull-stripping tool, and nothing else |
| `tests/`       | pytest unit tests |
| `source_data/` | Empty on purpose: inputs are read in place; see [`source_data/CONTENT.md`](source_data/CONTENT.md) |
| `output_data/` | Default `--output`: plan, masks, logs, metrics, report, Slurm files; see [`output_data/CONTENT.md`](output_data/CONTENT.md) |
| `tasks.py`     | The invoke tasks |
| `invoke.yaml`  | Config: default paths, report range, provenance |

---

## 🔒 Data

Masks, the report and per-run metrics show or describe participants' brains, so everything under the output folder stays out of git. Only `PROVENANCE.json` and `MANIFEST.json` are tracked, and only in `output_data/`. Keep it that way when running on restricted datasets.

---

## Philosophy

Inspired by Uncle Iroh from *Avatar: The Last Airbender*, `airoh` aims to bring simplicity, reusability, and clarity to research infrastructure — one well-structured task at a time.

When working in this project, Claude Code responds as **Uncle Airoh**: patient, warm, and wise.
