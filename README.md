# Skullstrip Bench

Skullstrip Bench runs several containerized skull-stripping tools (SynthStrip, FSL BET, SynthSeg, ANTs) on every T1w image of a BIDS dataset, then builds an HTML report in which you rate each brain mask. There is no ground truth: the final call is yours, and the metrics (mask volume, Dice against the consensus of all tools, runtime) are only there to guide the eye.

The tool never downloads anything. It runs the container images you already have and reads your files where they are, which is what lets it run on cluster compute nodes without internet access, such as those of the Digital Research Alliance of Canada. It runs locally with Docker or Apptainer, or on a Slurm cluster, where it writes job scripts with one array task per participant.

The project was built from the `airoh-mini` template. [airoh](https://github.com/SIMEXP/airoh) 🍵 is a small Python package of reusable [invoke](https://www.pyinvoke.org/) tasks for reproducible analyses, developed at SIMEXP. The template gives every project the same shape: a `tasks.py` holding the pipeline steps as invoke tasks, an `invoke.yaml` for paths and settings, `source_data/` for inputs and `output_data/` for results, provenance records written at each run, and a `verify` task that checks the code, the configuration and the documentation still agree. Its name is a nod to Uncle Iroh, from *Avatar: The Last Airbender*, and his love of tea.

Status: built during BrainHack School. All four tools work end to end under Docker, and the Slurm mode with nested Apptainer runs on the Narval cluster (Digital Research Alliance of Canada).

## Quick start

To run Skullstrip Bench on your own computer:

1. Install the Python environment with [uv](https://docs.astral.sh/uv/), which also installs the dev tools (flake8, pytest). You also need a container engine, Docker with its daemon running or Apptainer. Apptainer is used if available, otherwise Docker, and `--engine docker` forces one.

   ```bash
   uv sync
   ```

2. Put the images of the tools you want to compare in one folder, under the file names the tool looks for. With Docker:

   ```bash
   mkdir -p /path/to/images && cd /path/to/images
   docker pull --platform linux/amd64 freesurfer/synthstrip:1.8
   docker save -o synthstrip_1.8.tar freesurfer/synthstrip:1.8
   docker pull --platform linux/amd64 gamorosino/fsl:6.0.7.22
   docker save -o fsl_6.0.7.22.tar gamorosino/fsl:6.0.7.22
   docker pull --platform linux/amd64 cookpa/synthseg:conda-0.2
   docker save -o synthseg_conda-0.2.tar cookpa/synthseg:conda-0.2
   docker pull --platform linux/amd64 antsx/ants:latest
   docker save -o ants_latest.tar antsx/ants:latest
   ```

   Every image found in the folder is used, so leave out the tools you do not want. HALFpipe's image is only needed for `--reconall` (see [Recon-all, as in HALFpipe](#recon-all-as-in-halfpipe)).

3. Run the pipeline:

   ```bash
   uv run invoke run --bids /path/to/bids --containers /path/to/images --output /path/to/results
   ```

4. Open `report.html` in the output folder and rate the masks (see [Judging the masks](#judging-the-masks)).

### Inputs, outputs and reruns

You bring only your dataset and the container images; anything else a supported tool needs (such as the ANTs template) ships with Skullstrip Bench. The one exception is the optional `--reconall` comparison, which also needs your FreeSurfer license (see [Recon-all, as in HALFpipe](#recon-all-as-in-halfpipe)). The folders are read in place, nothing is copied or linked:

| Flag | What it points to |
| ---- | ----------------- |
| `--bids` | The BIDS dataset. Only `dataset_description.json` and the T1w images in each subject's anat folder (sessions allowed) are read. |
| `--containers` | A folder holding only container images: Docker archives `<name>.tar` (from `docker save`) and/or Apptainer `<name>.sif`, named as in [Compatible containers](#compatible-containers). |
| `--output` | Where the report goes (default `output_data/` in this repository). Use one output folder per dataset. |
| `--workdir` | Where the logs go, and with `--scheduler slurm` the sbatch script and `jobs.txt` (default: the directory you run the command from). |
| `--reconall` | Optional. Tools whose masks also go through recon-all the way HALFpipe does, each shown as an extra column (see [Recon-all, as in HALFpipe](#recon-all-as-in-halfpipe)). |

To avoid retyping the paths on one machine, set defaults under `inputs:` in `invoke.yaml`.

`run` first runs `run-check`, which launches nothing and takes seconds whatever the dataset size. The dataset check is shallow: it looks for `dataset_description.json`, the `sub-*` folders and the T1w files, and never opens an image, so a broken T1w simply fails its own run. Without `--tools`, every image in `--containers` that has a config in `tools/` is used, and the other images are reported as not compatible. `--tools synthstrip,fsl-bet` restricts the tools and `--subjects 10159,10171` the participants.

Then each participant is processed in turn. A run fails, is recorded, and the next one starts when the tool errors, runs out of memory, exceeds the tool's `timeout_min`, or produces a mask that is missing, not binary or off the T1w grid.

What you get is split between the output folder and the working directory:

```
<workdir>/                       the directory you run the command from
  logs/<tool>/<stem>.log         what the tool printed, after a first line with the exact command
  logs/<tool>/<stem>.err         its errors, ending with why the run failed if it did
  <output>/report.html           the report, one page for every participant
  <output>/figures/              its pictures, a thumbnail and a full-size version per run
  <output>/metrics.csv           volume, Dice, duration and status of each run
```

Everything the tool keeps for itself lives in the hidden folder `<output>/.skullstrip-bench/`: the plan, the record of each run (which is how a repeated `run` knows what is already done), the masks (needed to recompute the Dice when a run is retried or a tool added), the parts of the incremental report and the provenance records. The raw files each tool writes are deleted at the end of its run.

Every step skips work whose output already exists, so `run` is cheap to repeat. Failed runs count as done too, so a slow tool that crashed is not relaunched every time: retry them with `uv run invoke run-skullstrip --output … --retry-failed`, or redo one tool with `uv run invoke clean-skullstrip --output … --tools fsl-bet`. The other side of this is that editing the code does not re-run anything; `run … --force` cleans the output folder and starts over.

## Judging the masks

Open `report.html` in the output folder. The report is incremental: each participant is added as soon as its runs are done, so you can open it at any time, and reload it to see the participants finished since. The header says how many participants are processed.

The pictures are not inside the page: `report.html` points to the files in `figures/` next to it, and the browser only loads the thumbnails on screen, and a full-size picture when you click it. The page itself stays small, so hundreds of participants fit on it.

There is one row per T1w and one column per tool. Each cell shows the T1w with the mask's outline in red, in axial, coronal and sagittal views, with the same slices for every tool. Clicking a picture opens a high-resolution version: zoom with the mouse wheel, drag to move, and use the arrow keys to switch to another tool (left, right) or T1w (up, down) at the same zoom and position. Under each picture are the mask volume, highlighted outside the plausible range set in `invoke.yaml` (`report: plausible_volume_ml`, 1100 to 1600 mL by default), the Dice against the consensus of the tools, and the runtime. A failed run shows its error instead.

Rate each mask Good, Bad or Uncertain, add a comment if needed, then use Export ratings (CSV). Ratings are kept in your browser across reloads, including while the report keeps growing, but the CSV export is your real record.

To look at the report on another computer, copy `report.html` and `figures/` together (the output folder, without its hidden `.skullstrip-bench/`). It shows participants' brains, so copy or share it only where the dataset's rules allow.

## Running on a cluster

On a Slurm cluster you need neither Python nor this repository: the tool ships as one Apptainer image, `skullstrip-bench_<version>.sif`, which launches the tools' images from inside (Apptainer nested in Apptainer). The steps below were written on Narval; other clusters of the Digital Research Alliance of Canada work the same way.

1. On a login node (it has internet access), download the tool from the [releases](https://github.com/pbergeret12/skullstrip-bench/releases). Keep it outside your images folder, which must hold only the tools' images.

   ```bash
   cd $SCRATCH
   wget https://github.com/pbergeret12/skullstrip-bench/releases/download/v0.4.0/skullstrip-bench_v0.4.0.sif
   ```

2. Still on the login node, build the tools' images into one folder. The digests pin the exact images this project was tested with, and the file names are how the tool recognizes each image. Run this inside `tmux`, since it takes a while and must survive a dropped SSH connection.

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

   For `--reconall` only, add HALFpipe's image and your FreeSurfer license to the same folder:

   ```bash
   apptainer build halfpipe-1.3.1.sif docker://halfpipe/halfpipe@sha256:b3d4d714cca689541f02e88c7ae8cdd65ca5b23c9e060785e265bfad12b186ca
   cp ~/license.txt $SCRATCH/containers/license.txt
   ```

   If you already use HALFpipe, copying its existing `.sif` as `halfpipe-1.3.1.sif` works as well, as long as it is version 1.3.1.

3. From the directory you want to work in, still on the login node, generate the job script. This only checks the dataset and the images, then writes `skullstrip_bench_sbatch.sh` and `jobs.txt` (one participant per line); nothing is computed yet.

   ```bash
   mkdir -p $SCRATCH/my_study && cd $SCRATCH/my_study
   apptainer run --bind /path/to/bids,$SCRATCH/containers,$PWD $SCRATCH/skullstrip-bench_v0.4.0.sif run \
       --scheduler slurm --bids /path/to/bids --containers $SCRATCH/containers --output $PWD/results
   ```

   Add `--tools synthstrip,fsl-bet` to restrict the tools, `--subjects` to restrict the participants, and `--reconall synthseg,ants` for the recon-all columns.

4. Open `skullstrip_bench_sbatch.sh`, replace `def-CHANGEME` with your allocation (for example `def-yourpi`), and if you wish change `#SBATCH --array=1-N`: `1-20` for a pilot on the first 20 participants, `1-N%50` to run at most 50 at once. Then submit it:

   ```bash
   sbatch skullstrip_bench_sbatch.sh
   ```

5. Follow the run. Each array task processes one participant, every tool in turn, and adds it to `results/report.html` as soon as it is done, so the report can be opened at any time. The jobs' logs and each tool's logs are in `logs/`, next to the sbatch script. `seff <jobid>` shows the real memory and time used.

The resources of one task are computed from the selected tools: their largest CPU and memory needs, since they run one after the other, and a walltime of the sum of their durations × 1.5 + 10 min. After a pilot, generating the script again (step 3) replaces the durations written in the tools' configs by those measured on your cluster.

If something goes wrong:

- If Docker Hub answers "toomanyrequests" during step 2 (login nodes share one address), retry later or log in with `apptainer remote login --username <you> docker://docker.io`.
- The FSL and HALFpipe images are about 5 GB, and the login node may kill their build during the final compression. Build them in two steps instead: `apptainer build --sandbox fsl_sandbox docker://…` on the login node, then `apptainer build fsl_6.0.7.22.sif fsl_sandbox/` inside a job with a few cores, and delete the sandbox.
- Images you already have as `.tar` archives convert the same way, with `docker-archive://path/to/<name>.tar` instead of `docker://…`.
- Nested Apptainer needs unprivileged user namespaces on the compute nodes. If a cluster refuses them, run the tool from a Python environment on the cluster instead (clone this repository, `uv sync`, then `uv run invoke run …` with the same flags).

## Compatible containers

A container is compatible when `tools/` has a config for it. To run, its image must sit in `--containers` under the file name below; nothing else is needed from you.

| Tool | Image | File name in `--containers` | Output | Runtime per T1w (Mac, amd64 emulation) | Cluster resources |
| ---- | ----- | --------------------------- | ------ | -------------------------------------- | ----------------- |
| `synthstrip` | `freesurfer/synthstrip:1.8` | `synthstrip_1.8.tar` or `.sif` | brain mask (CSF included) | about 17 s | 4 CPUs, 8 GB |
| `fsl-bet` | `gamorosino/fsl:6.0.7.22` | `fsl_6.0.7.22.tar` or `.sif` | brain mask (`bet -m -R`) | about 8 s | 1 CPU, 2 GB |
| `synthseg` | `cookpa/synthseg:conda-0.2` | `synthseg_conda-0.2.tar` or `.sif` | segmentation (`--robust`) turned into a mask as in our HALFpipe pipeline: every label except the CSF around the brain (24), resampled onto the T1w grid | about 2 min on a cluster node | 8 CPUs, 16 GB |
| `ants` | `antsx/ants:latest` | `ants_latest.tar` or `.sif` | `antsBrainExtraction.sh` mask, with the OASIS template bundled in `container_requirements/ants/` | about 6.5 min | 8 CPUs, 8 GB |

On a machine with Docker, the images become `.tar` files as shown in [Quick start](#quick-start); on a cluster, build the `.sif` directly as shown in [Running on a cluster](#running-on-a-cluster).

The ANTs template (three files, 34 MB) is the OASIS template from the ANTs templates by Brian Avants and Nick Tustison on figshare ([doi:10.6084/m9.figshare.915436](https://doi.org/10.6084/m9.figshare.915436)), redistributed unchanged under the CC BY 4.0 license; see `container_requirements/ants/SOURCE.md`. It is part of the repository and of the tool's own container.

Under Docker on a Mac, SynthSeg needs at least 12 GB for the Docker virtual machine (it crashed with 8 GB), and long runs need free disk space: a full disk crashed Docker during development. The runtimes above were measured under amd64 emulation on an Apple Silicon Mac and are faster natively.

### Recon-all, as in HALFpipe

Skullstrip Bench exists first to choose the skull stripping fed to the HALFpipe preprocessing pipeline. With `run_reconall: true`, HALFpipe's fMRIPrep does not keep that mask: after FreeSurfer's recon-all, it rebuilds the brain mask from FreeSurfer's segmentation. Where FreeSurfer goes wrong, the final mask goes wrong too, whichever tool stripped the brain.

`--reconall synthseg,ants` shows that final mask next to each named tool's own, as an extra column (`synthseg+reconall`, `ants+reconall`). For every T1w, the T1w stripped with the tool's mask goes through fMRIPrep from HALFpipe's own image, anatomy only, with skull stripping skipped and recon-all on, as a pre-stripped T1w does in HALFpipe. The mask shown is fMRIPrep's final `desc-brain_mask`, put back on the T1w grid. These columns get a Dice against the consensus but do not vote in it, since they would count their tool twice.

This needs two more files in `--containers`: HALFpipe's image as `halfpipe-1.3.1.sif` (or `.tar`, from `halfpipe/halfpipe:1.3.1`), which already holds fMRIPrep, FreeSurfer and the templates, and your FreeSurfer license as `license.txt` (free from the FreeSurfer website; it is personal, so it cannot ship with this public project). Step 2 of [Running on a cluster](#running-on-a-cluster) shows how to get both. Without `--reconall`, neither is used. Recon-all takes several hours per T1w and per tool, so the sbatch walltime grows accordingly (8 CPUs, 16 GB). Cleaning a tool with `clean-skullstrip --tools synthseg` also cleans `synthseg+reconall`, which was made from its masks.

### Adding a tool

A tool is one YAML in `tools/` and its image in the containers folder. If it needs other files (an atlas, a template, a config), they go in `container_requirements/<tool>/` in this repository, so that they ship with the project and its container; users never have to provide them.

```yaml
# tools/mytool.yaml
name: mytool                        # must match the file name
image: someone/mytool:2.0           # Docker reference
container: mytool_2.0               # <containers>/mytool_2.0.tar or .sif
command: mytool --in {input} --mask {mask} --threads {threads}
# mask_output: "{output_prefix}_mask.nii.gz"   # if the tool picks its own mask name
# postprocess: labels_to_mask                    # if the tool outputs a segmentation (or synthseg_brain_mask)
# requires: [atlas.nii.gz]                       # files in container_requirements/mytool/
timeout_min: 30                     # stop a run stuck for 30 minutes
cpus: 4                             # cluster resources for one run
mem_gb: 8
minutes: 5                          # expected duration on a cluster node
```

Inside the container, `{input}` is the T1w, `{mask}` where to write the mask, `{output_prefix}` a prefix for tools that name their own outputs, `{requirements}` the tool's bundled files (read-only) and `{threads}` the number of cores it may use. The launcher also sets `OMP_NUM_THREADS` and `ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS`, so that a tool never grabs every core of a shared node. Do not write `${VAR}` in a command, since braces are placeholders here; `$VAR` works.

### Publishing a new version of the tool

For maintainers. Publishing a GitHub release builds the tool's `.sif` on GitHub's servers and attaches it to the release (`.github/workflows/release-sif.yml`); nothing has to be built or uploaded from your own machine:

```bash
gh release create v0.5.0 --target <branch or commit> --title "v0.5.0" --notes "What changed"
```

The release tag becomes the tool's version, recorded in every plan the tool writes. Update the version in the download command of [Running on a cluster](#running-on-a-cluster) at the same time. To work on the image locally instead, `uv run invoke build-image --output-dir /path/to/folder` builds it with Docker and saves it as `skullstrip-bench_<commit>.tar`, which `apptainer build skullstrip-bench.sif docker-archive://…` converts. The build downloads everything over https, because some institutional networks stall plain-http Ubuntu mirrors.

## Tasks

| Task               | Description |
| ------------------ | ----------- |
| `run`              | The whole pipeline: the check, then participant by participant the runs and the update of metrics and report. With `--scheduler slurm` (running on an HPC) it writes `skullstrip_bench_sbatch.sh` and `jobs.txt` in the working directory instead; `--reconall` adds the recon-all columns; `--force` cleans first. |
| `run-check`        | Checks the dataset (shallow), tools, images, engine and output without running anything, and writes the plan and the input record (hidden state); `--reconall` as for `run`. Always re-runs. |
| `run-skullstrip`   | Executes the plan, one container run per (T1w × tool); `--subjects`, `--tools`, `--retry-failed`, `--threads`, `--work-root`. |
| `run-metrics`      | Updates `metrics.csv` (volume, Dice against the consensus, duration and status of each run) for `--subjects` (default all), from per-participant parts. Always re-runs. |
| `run-report`       | Updates the report for `--subjects` (default all): draws their missing pictures, rewrites their rows and rebuilds `report.html` from per-participant parts. |
| `run-update`       | `run-metrics` then `run-report` for some participants, which is what each participant's job runs when it is done. |
| `run-aggregate`    | Rebuilds metrics and report for every participant, then the provenance record; useful once a cluster run has ended. |
| `run-smoke`        | A fast end-to-end pass: one T1w with SynthStrip, run locally. |
| `build-image`      | Builds the tool's own container locally (`docker build` and `docker save` into `skullstrip-bench_<version>.tar`). Releases are built by GitHub instead. |
| `prepare-images`   | Builds each tool's Apptainer `.sif` from its `.tar`, from a Python checkout. |
| `verify`           | Checks that code, configuration, data and documentation still agree. |
| `clean`            | Removes all computed outputs of an output folder, and the logs and Slurm files of a working directory. |
| `clean-check`      | Removes the plan and the input record. |
| `clean-skullstrip` | Removes the runs' logs, masks and records and their report pictures; `--tools` limits it to some tools (and their `+reconall` columns). |
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
