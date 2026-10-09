# Skullstrip Bench

Skullstrip Bench runs several containerized skull-stripping tools (SynthStrip, FSL BET, SynthSeg, ANTs) on every T1w image of a BIDS dataset, then builds a self-contained HTML report in which you rate each brain mask. There is no ground truth: the final call is yours, and the metrics (mask volume, Dice against the consensus of all tools, runtime) are only there to guide the eye.

The tool never downloads anything. It runs the container images you already have and reads your files where they are, which is what lets it run on cluster compute nodes without internet access, such as those of the Digital Research Alliance of Canada. It runs locally with Docker or Apptainer, or on a Slurm cluster, where it writes job scripts with one array task per participant.

The project was built from the `airoh-mini` template. [airoh](https://github.com/SIMEXP/airoh) 🍵 is a small Python package of reusable [invoke](https://www.pyinvoke.org/) tasks for reproducible analyses, developed at SIMEXP. The template gives every project the same shape: a `tasks.py` holding the pipeline steps as invoke tasks, an `invoke.yaml` for paths and settings, `source_data/` for inputs and `output_data/` for results, provenance records written at each run, and a `verify` task that checks the code, the configuration and the documentation still agree. Its name is a nod to Uncle Iroh, from *Avatar: The Last Airbender*, and his love of tea.

Status: built during BrainHack School. All four tools work end to end under Docker, and the tool's own container has run Apptainer successfully. The Slurm mode and nested Apptainer have not run on a real cluster yet.

## Quick start

Install the Python environment with [uv](https://docs.astral.sh/uv/), which also installs the dev tools (flake8, pytest). You also need a container engine, Docker with its daemon running or Apptainer. Apptainer is used if available, otherwise Docker, and `--engine docker` forces one.

```bash
uv sync
uv run invoke run --bids /path/to/bids --containers /path/to/images --output /path/to/results
```

You bring only your dataset and the container images; anything else a supported tool needs (such as the ANTs template) ships with Skullstrip Bench. The folders are read in place, nothing is copied or linked:

| Flag | What it points to |
| ---- | ----------------- |
| `--bids` | The BIDS dataset. Only `dataset_description.json` and the T1w images in each subject's anat folder (sessions allowed) are read. |
| `--containers` | A folder holding only container images: Docker archives `<name>.tar` (from `docker save`) and/or Apptainer `<name>.sif`, named as in [Compatible containers](#compatible-containers). |
| `--output` | Where the report goes (default `output_data/` in this repository). Use one output folder per dataset. |
| `--workdir` | Where the logs go, and with `--scheduler slurm` the sbatch script and `jobs.txt` (default: the directory you run the command from). |

To avoid retyping the paths on one machine, set defaults under `inputs:` in `invoke.yaml`.

`run` first runs `run-check`, which launches nothing and takes seconds whatever the dataset size. The dataset check is shallow: it looks for `dataset_description.json`, the `sub-*` folders and the T1w files, and never opens an image, so a broken T1w simply fails its own run. Without `--tools`, every image in `--containers` that has a config in `tools/` is used, and the other images are reported as not compatible. `--tools synthstrip,fsl-bet` restricts the tools and `--subjects 10159,10171` the participants.

Then each participant is processed in turn. A run fails, is recorded, and the next one starts when the tool errors, runs out of memory, exceeds the tool's `timeout_min`, or produces a mask that is missing, not binary or off the T1w grid.

What you get is split between the output folder and the working directory:

```
<workdir>/                       the directory you run the command from
  logs/<tool>/<stem>.log         what the tool printed, after a first line with the exact command
  logs/<tool>/<stem>.err         its errors, ending with why the run failed if it did
  <output>/report.html           the report's entry page, listing its pages
  <output>/pages/                the report's pages, a few participants each
  <output>/figures/              its pictures, a thumbnail and a full-size version per run
  <output>/metrics.csv           volume, Dice, duration and status of each run
```

Everything the tool keeps for itself lives in the hidden folder `<output>/.skullstrip-bench/`: the plan, the record of each run (which is how a repeated `run` knows what is already done), the masks (needed to recompute the Dice when a run is retried or a tool added), the parts of the incremental report and the provenance records. The raw files each tool writes are deleted at the end of its run.

Every step skips work whose output already exists, so `run` is cheap to repeat. Failed runs count as done too, so a slow tool that crashed is not relaunched every time: retry them with `uv run invoke run-skullstrip --output … --retry-failed`, or redo one tool with `uv run invoke clean-skullstrip --output … --tools fsl-bet`. The other side of this is that editing the code does not re-run anything; `run … --force` cleans the output folder and starts over.

## Judging the masks

Open `report.html` in the output folder. The report is incremental: each participant is added as soon as its runs are done, so you can open it at any time, and reload it to see the participants finished since. The header says how many participants are processed.

`report.html` lists the pages of the report and how many of their participants are processed. Every picture is embedded, about 5 MB per participant with four tools, so the report is split into pages of 20 participants by default: choose another size with `--per-page N` when you run the tool, or set `report: participants_per_page` in `invoke.yaml`. To find the size your browser handles comfortably, `uv run invoke run-report --output … --per-page N` splits an existing report again in seconds, without recomputing anything; the new size is kept for the participants still to come.

On each page there is one row per T1w and one column per tool. Each cell shows the T1w with the mask's outline in red, in axial, coronal and sagittal views, with the same slices for every tool. Clicking a picture opens a high-resolution version: zoom with the mouse wheel, drag to move, and use the arrow keys to switch to another tool (left, right) or T1w (up, down) at the same zoom and position. Under each picture are the mask volume, highlighted outside the plausible range set in `invoke.yaml` (`report: plausible_volume_ml`, 1100 to 1600 mL by default), the Dice against the consensus of the tools, and the runtime. A failed run shows its error instead.

Rate each mask Good, Bad or Uncertain, add a comment if needed, then use Export ratings (CSV), page by page. Ratings are kept in your browser across reloads, including while the report keeps growing, but the CSV export is your real record.

The file is self-contained (images embedded) and can be sent as is. It shows participants' brains, though, so share it only where the dataset's rules allow.

## Running with Apptainer and Slurm

On a cluster you need neither Python nor this repository: the tool ships as one image, `skullstrip-bench.sif`, holding the Python environment, the code, the tool configs and Apptainer itself, so that it can launch the skull-stripping containers from inside (Apptainer nested in Apptainer). Every task works as with `uv run invoke`, provided the folders it reads or writes are bound into the container at the same path. The tool's own image never goes in `--containers`, which only holds the images it runs.

Nested Apptainer requires unprivileged user namespaces on the compute nodes, which is how current Apptainer installations without setuid work. If a cluster refuses it, run the tool from a Python environment on the cluster instead (`uv sync`, then `uv run invoke …`); everything else stays the same.

### Preparing the images

The tool itself is one file, `skullstrip-bench_<version>.sif`, published with each [release](https://github.com/pbergeret12/skullstrip-bench/releases). Download it once on a login node, which has internet access, and store it wherever you keep your images (outside the folder you pass as `--containers`):

```bash
wget https://github.com/pbergeret12/skullstrip-bench/releases/download/<version>/skullstrip-bench_<version>.sif
```

The skull-stripping images are built directly on the login node from Docker Hub. The digests pin the exact images this project was tested with, and the file names are how the tool recognizes each image. Run this inside `tmux`, so that it survives a dropped SSH connection.

```bash
module load apptainer
# Temporary files and cache on $SCRATCH: $HOME has a small quota.
export APPTAINER_TMPDIR=$SCRATCH/apptainer_tmp APPTAINER_CACHEDIR=$SCRATCH/apptainer_cache
mkdir -p $APPTAINER_TMPDIR $APPTAINER_CACHEDIR $SCRATCH/containers
cd $SCRATCH/containers

apptainer build synthstrip_1.8.sif     docker://freesurfer/synthstrip@sha256:ebbc177221194371f16362513ace68312a22922bb581bdfa618ac7ff9c1d2c06
apptainer build fsl_6.0.7.22.sif       docker://gamorosino/fsl@sha256:e17b13fe4af7ec79643595bb2de16584193234b99cb2fafbd7c786a1dc8b8d43
apptainer build synthseg_conda-0.2.sif docker://cookpa/synthseg@sha256:4c632dd3c7591e72b4b87357449e50cc96cc29cef92326db879264be107dd4c9
apptainer build ants_latest.sif        docker://antsx/ants@sha256:59c45f54a1f1dc69134f63bec91a726e41c71c64a16cc21cda0b54526910a3c3
```

If Docker Hub answers "toomanyrequests" (login nodes share one address), retry later or log in with `apptainer remote login --username <you> docker://docker.io`. Images you already have as `.tar` archives convert the same way, with `docker-archive://path/to/<name>.tar`.

### Publishing a new version of the tool

For maintainers. Publishing a GitHub release builds the tool's `.sif` on GitHub's servers and attaches it to the release (`.github/workflows/release-sif.yml`); nothing has to be built or uploaded from your own machine:

```bash
gh release create v0.2.0 --target <branch or commit> --title "v0.2.0" --notes "What changed"
```

The release tag becomes the tool's version, recorded in every plan the tool writes. To work on the image locally instead, `uv run invoke build-image --output-dir /path/to/folder` builds it with Docker and saves it as `skullstrip-bench_<commit>.tar`, which `apptainer build skullstrip-bench.sif docker-archive://…` converts. The build downloads everything over https, because some institutional networks stall plain-http Ubuntu mirrors.

### Testing on a compute node

Before a real run, one small job checks on a compute node that the tool's container runs, that nested Apptainer works there, and that two participants go through end to end with the two fast tools. Save it as `test_skullstrip_bench.sh`, fill in the paths and the account, then `sbatch test_skullstrip_bench.sh`.

```bash
#!/bin/bash
#SBATCH --account=def-yourpi
#SBATCH --job-name=skullstrip-bench-test
#SBATCH --cpus-per-task=4
#SBATCH --mem=8G
#SBATCH --time=01:00:00
#SBATCH --output=skullstrip-bench-test_%j.log
#SBATCH --error=skullstrip-bench-test_%j.err
set -euo pipefail

TOOL_SIF=/path/to/skullstrip-bench.sif
BIDS=/path/to/bids_dataset
CONTAINERS=/path/to/containers          # holds synthstrip_1.8.sif and fsl_6.0.7.22.sif
OUTPUT=$SCRATCH/skullstrip_bench_test
SUBJECTS=10159,10171                    # two participants of the dataset

module load apptainer
export APPTAINER_TMPDIR=$SLURM_TMPDIR
mkdir -p "$OUTPUT"
binds="$BIDS,$CONTAINERS,$OUTPUT,$SLURM_TMPDIR"

echo "Tool version: $(apptainer exec "$TOOL_SIF" cat /opt/skullstrip-bench/VERSION)"

echo "Nested Apptainer check:"
apptainer exec --bind "$binds" "$TOOL_SIF" \
    apptainer exec "$CONTAINERS/synthstrip_1.8.sif" mri_synthstrip --help | head -3

apptainer run --bind "$binds" "$TOOL_SIF" run \
    --bids "$BIDS" --containers "$CONTAINERS" --output "$OUTPUT" \
    --tools synthstrip,fsl-bet --subjects "$SUBJECTS"
```

If the nested check fails, the job stops there (`set -e`) and its output shows Apptainer's message, which is what to send to the cluster's support. Otherwise the report in the output folder holds the two participants, and the tools' logs are in `logs/` in the directory you submitted the job from.

### Running a whole dataset

`--scheduler slurm` is the flag that says the tool runs on an HPC. Without it, everything runs locally and the tool produces the report. With it, the tool computes nothing: after the check, it writes one sbatch script that processes the participants in parallel. Run it on a login node, from the directory you want to work in:

```bash
cd $SCRATCH/my_study
module load apptainer
apptainer run --bind /path/bids,/path/containers,$PWD skullstrip-bench.sif run \
    --scheduler slurm --bids /path/bids --containers /path/containers --output $PWD/results \
    --tools synthstrip,fsl-bet
```

This writes two files in the working directory, and the jobs will write their logs next to them:

| File | Content |
| ---- | ------- |
| `skullstrip_bench_sbatch.sh` | The job array, the only thing to submit. One task is one participant: every selected tool on all of that participant's T1w images, working on the node's local disk (`$SLURM_TMPDIR`) with the threads Slurm granted, after which the participant is added to the report and the metrics in `results/`. |
| `jobs.txt` | One participant per line (`sub-XX`). Array task N processes line N. |
| `logs/` | The jobs' own `slurm_<job>_<task>.log` and `.err`, and each tool's `.log` and `.err`. |

Open `skullstrip_bench_sbatch.sh` and replace `def-CHANGEME` with your allocation (for example `def-yourpi`). The array line, `#SBATCH --array=1-N`, runs every participant of `jobs.txt`; change it to `1-20` for a pilot on the first 20, or `1-N%50` to run at most 50 at once. Then submit it:

```bash
sbatch skullstrip_bench_sbatch.sh
```

There is no separate report job: each task adds its participant to `results/report.html` as soon as it is done, so the report can be opened at any time. The resources of one task are filled in from the selected tools: the largest CPU and memory needs, since the tools run one after the other, and a walltime of the sum of their durations × 1.5 + 10 min. Durations come from each tool's YAML, or from durations already measured with Apptainer in that output folder, so after a pilot, generating the script again gives walltimes that fit the cluster. `seff <jobid>` shows the real memory peak.

## Compatible containers

A container is compatible when `tools/` has a config for it. To run, its image must sit in `--containers` under the file name below; nothing else is needed from you.

| Tool | Image | File name in `--containers` | Output | Runtime per T1w (Mac, amd64 emulation) | Cluster resources |
| ---- | ----- | --------------------------- | ------ | -------------------------------------- | ----------------- |
| `synthstrip` | `freesurfer/synthstrip:1.8` | `synthstrip_1.8.tar` or `.sif` | brain mask (CSF included) | about 17 s | 4 CPUs, 8 GB |
| `fsl-bet` | `gamorosino/fsl:6.0.7.22` | `fsl_6.0.7.22.tar` or `.sif` | brain mask (`bet -m -R`) | about 8 s | 1 CPU, 2 GB |
| `synthseg` | `cookpa/synthseg:conda-0.2` | `synthseg_conda-0.2.tar` or `.sif` | segmentation turned into a mask: every label above 0 (CSF included), resampled onto the T1w grid | 3 to 5 min | 8 CPUs, 16 GB |
| `ants` | `antsx/ants:latest` | `ants_latest.tar` or `.sif` | `antsBrainExtraction.sh` mask, with the OASIS template bundled in `container_requirements/ants/` | about 6.5 min | 8 CPUs, 8 GB |

On a machine with Docker, an image becomes a `.tar` with `docker pull <image> && docker save -o <file name>.tar <image>`; on a cluster, build the `.sif` directly as shown in [Preparing the images](#preparing-the-images).

The ANTs template (three files, 34 MB) is the OASIS template from the ANTs templates by Brian Avants and Nick Tustison on figshare ([doi:10.6084/m9.figshare.915436](https://doi.org/10.6084/m9.figshare.915436)), redistributed unchanged under the CC BY 4.0 license; see `container_requirements/ants/SOURCE.md`. It is part of the repository and of the tool's own container.

Building the FSL image (about 5 GB) on a cluster login node can be killed by the node's limits during its long compression step. Build it in two steps instead: `apptainer build --sandbox fsl_sandbox docker://…` on the login node (download and extraction only, a few minutes), then `apptainer build fsl_6.0.7.22.sif fsl_sandbox/` inside a job with a few cores, and delete the sandbox.

Under Docker on a Mac, SynthSeg needs at least 12 GB for the Docker virtual machine (it crashed with 8 GB), and long runs need free disk space: a full disk crashed Docker during development. The runtimes above were measured under amd64 emulation on an Apple Silicon Mac and are faster natively.

### Adding a tool

A tool is one YAML in `tools/` and its image in the containers folder. If it needs other files (an atlas, a template, a config), they go in `container_requirements/<tool>/` in this repository, so that they ship with the project and its container; users never have to provide them.

```yaml
# tools/mytool.yaml
name: mytool                        # must match the file name
image: someone/mytool:2.0           # Docker reference
container: mytool_2.0               # <containers>/mytool_2.0.tar or .sif
command: mytool --in {input} --mask {mask} --threads {threads}
# mask_output: "{output_prefix}_mask.nii.gz"   # if the tool picks its own mask name
# postprocess: labels_to_mask                    # if the tool outputs a segmentation
# requires: [atlas.nii.gz]                       # files in container_requirements/mytool/
timeout_min: 30                     # stop a run stuck for 30 minutes
cpus: 4                             # cluster resources for one run
mem_gb: 8
minutes: 5                          # expected duration on a cluster node
```

Inside the container, `{input}` is the T1w, `{mask}` where to write the mask, `{output_prefix}` a prefix for tools that name their own outputs, `{requirements}` the tool's bundled files (read-only) and `{threads}` the number of cores it may use. The launcher also sets `OMP_NUM_THREADS` and `ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS`, so that a tool never grabs every core of a shared node. Do not write `${VAR}` in a command, since braces are placeholders here; `$VAR` works.

## Tasks

| Task               | Description |
| ------------------ | ----------- |
| `run`              | The whole pipeline: the check, then participant by participant the runs and the update of metrics and report. With `--scheduler slurm` (running on an HPC) it writes `skullstrip_bench_sbatch.sh` and `jobs.txt` in the working directory instead; `--force` cleans first. |
| `run-check`        | Checks the dataset (shallow), tools, images, engine and output without running anything, and writes the plan and the input record (hidden state). Always re-runs. |
| `run-skullstrip`   | Executes the plan, one container run per (T1w × tool); `--subjects`, `--tools`, `--retry-failed`, `--threads`, `--work-root`. |
| `run-metrics`      | Updates `metrics.csv` (volume, Dice against the consensus, duration and status of each run) for `--subjects` (default all), from per-participant parts. Always re-runs. |
| `run-report`       | Updates the report for `--subjects` (default all): draws their missing pictures, rewrites their rows and rebuilds their page and `report.html` from per-participant parts. `--per-page N` splits the existing report again. |
| `run-update`       | `run-metrics` then `run-report` for some participants, which is what each participant's job runs when it is done. |
| `run-aggregate`    | Rebuilds metrics and report for every participant, then the provenance record; useful once a cluster run has ended. |
| `run-smoke`        | A fast end-to-end pass: one T1w with SynthStrip, run locally. |
| `build-image`      | Builds the tool's own container locally (`docker build` and `docker save` into `skullstrip-bench_<version>.tar`). Releases are built by GitHub instead. |
| `prepare-images`   | Builds each tool's Apptainer `.sif` from its `.tar`, from a Python checkout. |
| `verify`           | Checks that code, configuration, data and documentation still agree. |
| `clean`            | Removes all computed outputs of an output folder, and the logs and Slurm files of a working directory. |
| `clean-check`      | Removes the plan and the input record. |
| `clean-skullstrip` | Removes the runs' logs, masks and records and their report pictures; `--tools` limits it to some tools. |
| `clean-metrics`    | Removes `metrics.csv` and its parts. |
| `clean-report`     | Removes the report, its parts and its pictures. |
| `clean-slurm`      | Removes `skullstrip_bench_sbatch.sh`, `jobs.txt` and the jobs' own logs from the working directory. |

Every task that reads or writes results takes `--output` (default `output_data/`), and those that write logs or Slurm files take `--workdir` (default the current directory). `uv run invoke --list` and `uv run invoke --help <task>` give the details. The checks used during development are `uv run invoke run-smoke --bids … --containers …`, `uv run invoke verify`, `uv run pytest` and `uv run flake8`.

## Folder structure

| Folder or file | Description |
| -------------- | ----------- |
| `analysis/`    | The processing code called by the tasks: BIDS parsing, mask validation, tool configs, the container launcher (the only module aware of the engine), the checks, the Slurm script writer, metrics and report |
| `tools/`       | One YAML per skull-stripping tool, and nothing else |
| `tests/`       | pytest unit tests |
| `Dockerfile`, `container/` | The tool's own container (Python environment, code, Apptainer) and its entry point |
| `.github/workflows/` | Builds the tool's `.sif` and attaches it to each GitHub release |
| `source_data/` | Empty on purpose, since inputs are read in place; see [`source_data/CONTENT.md`](source_data/CONTENT.md) |
| `output_data/` | The default `--output`; see [`output_data/CONTENT.md`](output_data/CONTENT.md) |
| `tasks.py`     | The invoke tasks |
| `container_requirements/` | Files the supported tools need besides their image, one subfolder per tool (the ANTs template) |
| `invoke.yaml`  | Configuration: default paths, report range, provenance |

## Data

The report, the metrics, the logs and the hidden masks show or describe participants' brains, so they stay out of git: everything under the output folder except the two provenance records in `output_data/.skullstrip-bench/`, and the `logs/`, `jobs.txt` and sbatch script a run writes in its working directory. Keep it that way when running on restricted datasets.
