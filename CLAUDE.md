# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

**Skullstrip Bench** runs several containerized skull-stripping tools (SynthStrip, FSL BET, SynthSeg, ANTs) on every T1w image of a BIDS dataset, then builds a self-contained HTML report in which a human rates each brain mask. There is no ground truth: metrics (mask volume, Dice against the majority-vote consensus, runtime) only guide the eye. Two priorities override everything else: **zero setup, no downloads by the tool**, and **extremely readable processing code**.

It is built on the [`invoke`](https://www.pyinvoke.org/) task runner and the `airoh` package of reusable invoke tasks, customized via `tasks.py` and `invoke.yaml` (an `airoh-mini` template project).

## Writing style for user-facing docs

README.md and the CONTENT.md files are written in plain prose. They use no emojis (one exception: the cup next to airoh in the README's introduction), no em dashes, no horizontal rules, and few bold words. The user finds those read as machine-written. Prefer sentences to bullet lists when the content is a description rather than a sequence of steps. Never add example scripts (`.sh`) to the repository: usage examples go in the README as code blocks.

## Persona

Respond as Uncle Airoh: patient, warm, and wise. Assume the user may be new to coding. Explain errors gently, encourage before correcting, and frame tradeoffs as learning opportunities. When things get heated, offer a calming cup of jasmine tea.

## Setup

```bash
uv sync    # installs runtime deps plus the dev group (flake8, pytest)
```

External requirements: Docker (with its daemon running) **or** Apptainer. Container images are never downloaded: they come from a folder of `.tar` (`docker save`) and/or `.sif` files.

## Common Commands

```bash
# Every task that reads or writes results takes --output (default: output_data/).
uv run invoke run-check --bids PATH --containers PATH [--output PATH]
                              # Check everything (shallow), write the plan (hidden state); runs nothing
uv run invoke run --bids PATH --containers PATH [--output PATH] \
                  [--tools a,b] [--subjects 01,02] [--engine docker|apptainer]
                              # Full pipeline, locally (cached: skips runs already done)
uv run invoke run … --scheduler slurm   # Write Slurm scripts (hidden state) instead of running
uv run invoke run … --force   # Clean everything first, then run from scratch
uv run invoke prepare-images --containers PATH   # Build .sif files once (cluster login node)
uv run invoke build-image     # The tool's own container: docker build + save → .tar
apptainer run --bind … skullstrip-bench.sif run …   # Same tasks from the tool's .sif
uv run invoke run-smoke --bids PATH --containers PATH   # 1 T1w × SynthStrip, end to end
uv run invoke verify          # Check code, config, data and docs still agree
uv run invoke clean           # Remove an output folder's computed contents
uv run invoke --list          # Show all available tasks
uv run pytest                 # Unit tests (tests/)
uv run flake8                 # Linter (configured in setup.cfg)
```

## Architecture

**Always read `tasks.py` first** before proposing or implementing any pipeline change — it is the authoritative source of what tasks exist, how they are wired, and what parameters they accept.

**Execution flow:** `invoke run` triggers the project's analysis pipeline by calling each step in its body, in order. The permanent tasks — `run`, `verify`, `clean` — are always present; intermediate steps are project-specific. The airoh template also has a `fetch` task; this project deliberately does not (see **No fetch step**).

**`pre=` chains do not fire when a task is called as a function.** A `pre=` list only runs when invoke executes that task from the command line. `run(c)` or `clean(c)` called from Python executes the body alone — so a `clean` whose real work lives entirely in `pre=` deletes nothing when `run --force` calls it, silently and with a success message. Umbrella tasks that other tasks call therefore do their work in the body. Keep `pre=` only where the task is purely a command-line entry point (never called by another task), and remember that anything threading a flag through — `--force`, `--smoke`, a chunk selector — must call its steps directly, since a `pre=` chain has already run by the time the body sees the flag.

**No fetch step.** The airoh template gathers inputs with `fetch` tasks (download, or symlink into `source_data/`). This project removed them on purpose. It must run on cluster compute nodes without internet (Digital Research Alliance of Canada, among others), so it never downloads anything, and it reads its inputs in place: `--bids` and `--containers`, with defaults under `inputs:` in `invoke.yaml`. `run-check` records what those paths resolved to (and their git commit when they are repositories) in `<output>/MANIFEST.json`, through airoh's `record_sources`. Do not reintroduce a download step, or a library that fetches resources at runtime (e.g. templateflow): anything a tool needs besides its image ships with the project (see **The user brings only images and a dataset**).

- `invoke.yaml` — config: `inputs:` (defaults for --bids and --containers), `requirements_dir` (the bundled container_requirements/), `output_data_dir` (default --output), `tools_dir`, the report's plausible volume range, provenance file names
- `tasks.py` — project-specific invoke tasks; uses `airoh.provenance` (input and run records) and `airoh.verify`
- `analysis/` — pure Python analysis logic, called by tasks in `tasks.py`
- `tools/` — one YAML per skull-stripping tool, and nothing else (see **Skullstrip Bench specifics** below)
- `tests/` — pytest unit tests for the pure logic in `analysis/`
- `source_data/CONTENT.md` and `output_data/CONTENT.md` — authoritative docs for what each data folder contains; update these when data assets change, do not duplicate their content elsewhere
- `.claude/skills/` — each skill exists twice: as a directory (the source you edit) and as a `.zip` (what gets copied into projects created from this template). **Re-zip after editing a skill**, or projects keep receiving the old version — this has already happened once: `cd .claude/skills && zip -qr <name>.zip <name> -x '*/.*'`

**Analysis in code:** All computation belongs in `analysis/` Python code, invoked by `run-{name}` tasks, which write results to `output_data/`. This project has no notebooks (the visual output is the HTML report); one may be added at the end for a summary figure, in which case restore the template's `run-notebooks` pattern (each notebook writes into its own folder under figures/, which is its "already ran" marker).

**Idempotent tasks:** Each `run-{name}` task must check whether its outputs already exist and skip execution if they do. This means `invoke run` can be called repeatedly during development of a later step — earlier steps are skipped automatically.

**Caching is by existence, and forcing is a sledgehammer.** A step skips when its output file is there; nothing compares timestamps or hashes against its inputs. That is a deliberate ceiling on complexity — a real dependency graph is more than this template wants to explain, and a cache nobody understands is worse than one that is occasionally too eager. The consequence is that **editing a script or a tool config does not invalidate anything**: the pipeline will happily skip the step you just changed. Two ways out, both explicit:

- `invoke clean-{name}` then `invoke run` — redo one step.
- `invoke run --force` — clean everything, then run from scratch.

When results start looking stale or inconsistent, reach for `--force` rather than trying to reason about what is cached. Do not add content-hash invalidation or a dependency graph to `run`; that is the workflow-engine road, and this template deliberately stops short of it.

**Task naming conventions:**
- Analysis tasks are named `run-{name}` (e.g. `run-preprocessing`, `run-model`).
- Cleaning tasks mirror them: `clean-{name}` removes only the outputs of the corresponding step. Granular clean tasks are what make a selective re-run possible, so every run step needs one.
- The top-level `clean` task calls all `clean-{name}` tasks in its body — it only ever touches the output folder (`--output`), never the inputs, which are read in place.
- The top-level `run` task calls all steps in its body, in order.
- `verify` checks the project against its own documentation; see **Verification**.

**Task parameters:** `run-{name}` tasks should expose chunk or subset parameters (e.g. a subject ID, a chunk index) so that individual pieces can be rerun in isolation. They should also support a `smoke` flag for a fast minimal run useful for testing the pipeline end-to-end without running the full analysis.

## Skullstrip Bench specifics

**The output folder shows only `report/` and `logs/`** (`analysis/layout.py` decides every path). The user asked for exactly this, so do not add visible outputs:
- `report/` holds `report.html`, `figures/` and `metrics.csv`;
- `logs/<tool>/<stem>.log` holds the container's stdout, after a `# command` line and before a final `# skullstrip-bench: <status>` line;
- `.err` holds its stderr, plus the failure reason;
- `logs/slurm/` holds the jobs' `.log`/`.err`.

Everything internal lives in the hidden `.skullstrip-bench/`: plan, run records, masks, report and metrics parts, Slurm scripts, MANIFEST/PROVENANCE. Masks are kept there, not in the visible output, because a retried run or an added tool changes the consensus, so every Dice of that T1w has to be recomputed from all its masks. Raw tool outputs go to a scratch folder deleted at the end of each run.

**Validation is separate from processing.** `run-check` verifies everything up front and writes the plan (`.skullstrip-bench/plan.json`): the input paths, the engine, the scheduler, the participants (`subjects`), the usable tool configs, and one entry per (T1w × tool) run with every path it reads or writes already decided (`t1w`, `mask`, `record`, `log`, `work_dir`). `run-skullstrip` executes that plan blindly. Its code assumes valid inputs and must stay extremely simple: one `try`/`except` per run, no re-validation. A new check belongs in `run-check`, not in the processing code. The dataset check is **shallow on purpose** (folder layout only, no image opened) so it takes seconds on a huge dataset; a broken T1w just fails its own run. Without `--tools`, the tools are the images found in `--containers` that have a config in `tools/` and whose `requires` files are present; other images are reported "not compatible" and skipped. `run-check` and `run-metrics` are the deliberate exceptions to existence-based caching: both always re-run. `run-check` is cheap and must see a newly added tool or image. `run-metrics` takes seconds, and the consensus (hence every Dice) changes whenever a run is added, so a cached table would silently go stale.

**The report** (`analysis/report.py`, `analysis/report_figures.py`, `analysis/report_template.html`, `analysis/assemble.py`) uses nilearn `plot_anat` plus `add_contours`, deliberately not niworkflows' `SimpleShowMaskRPT` (as in HALFpipe), whose nipype/templateflow stack can download templates. Slices are chosen from the T1w alone, so every tool is shown on the same slices. Each run's picture is drawn once and saved twice, as JPEG: a thumbnail for the grid (output_data/figures/TOOL/STEM.jpg) and a 300 dpi version (STEM_full.jpg, about 2 px per 1 mm voxel) that only the zoom viewer shows, with wheel zoom, drag, and arrow keys that move to the neighbouring cell at the same zoom and position. Both are cached and belong to their mask: `clean-skullstrip --tools x` removes it too. The HTML is rebuilt on every `run-report`. The template is filled by `string.Template`, so a literal dollar sign in it must be doubled. Its JavaScript is plain ES5 with no external resources, so the file works offline and can be shared alone.

**The report and the metrics are incremental.** The consensus only involves one T1w, so everything about a participant is computed in that participant's own job (`run-update --subjects X`). The job writes its parts — metrics_parts/SUBJECT.csv, and report_parts/SUBJECT.html with its pictures embedded — then rebuilds `metrics.csv` and `report.html` from every part present (`analysis/assemble.py`). Concurrent jobs are safe enough:
- writes are atomic (temporary file, then rename), so an open report is never half-written;
- after writing, the parts are listed again (names and modification times), and the file is rebuilt if anything changed meanwhile;
- the final report job (`run-aggregate`) rebuilds everything.

Locally, `run` goes participant by participant the same way. Only the plan's tools (`plan["tools"]`) appear in the report and enter the consensus, even if older runs of other tools sit in the output folder. Ratings are Good / Bad / Uncertain; they live in the browser's localStorage (key `skullstrip-bench-ratings`, per stem|tool), so they survive the report being rebuilt.

**Metrics guide the eye, they do not judge.** The consensus is a voxel-wise majority vote (strictly more than half) of the tools that succeeded on a T1w. With only two tools it is their intersection, which favors the more conservative mask: read Dice with that in mind until more tools are in.

**Engine logic lives only in `analysis/launcher.py`.** Docker (`docker run --rm --platform linux/amd64 --entrypoint "" -v …`) and Apptainer (`apptainer exec --compat --bind …`) are at parity, auto-detected (Apptainer first) or forced with `run-check --engine`. Images are never downloaded: Docker `docker load -i <name>.tar` if the image is not loaded yet; Apptainer uses `<name>.sif`, building it once from `<name>.tar` (`apptainer build <name>.sif docker-archive://<name>.tar`) inside the containers folder and keeping it. Containers write only into mounted folders. Dev machine: macOS (Apple Silicon) + Docker, so amd64 images run emulated; Apptainer is tested in a Lima VM and on the cluster.

**The user brings only images and a dataset.** This is a hard requirement from the user, stated more than once:
- a user provides nothing but the container images of supported tools and a BIDS dataset;
- anything a supported tool needs besides its image (atlas, template, config file) ships with Skullstrip Bench, in `container_requirements/<tool>/`, both in the repository and in the tool's own container (`requirements_dir` in `invoke.yaml`, resolved from `PROJECT_DIR`);
- there is no `--requirements` flag, and there must never be one;
- `tests/test_tool_configs.py` fails if a tool's `requires:` file is not bundled.

ANTs' OASIS template (32 MB, CC BY 4.0, see `container_requirements/ants/SOURCE.md`) is tracked in git on purpose, exempted in `verify.ignore_paths`. Inside the tool's container the requirements live in the image, so the Slurm scripts do not bind them.

**Adding a tool = one YAML in `tools/` + its image in the containers folder** (+ its extra files in `container_requirements/<tool>/`, if any). Keys: `name` (must equal the file name), `image` (Docker reference), `container` (image file base name), `command` (the full command, with placeholders `{input}`, `{mask}`, `{output_prefix}`, `{requirements}`, `{threads}` resolved to container paths/values). Optional keys: `mask_output` (default `{mask}`), `postprocess` (`labels_to_mask`), `requires` (file names expected in `container_requirements/<name>/`, mounted read-only as `{requirements}`), `timeout_min`, and the cluster resources of one run: `cpus`, `mem_gb`, `minutes`. Nothing but YAML lives in `tools/`. The launcher caps threads in every container through `OMP_NUM_THREADS` and `ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS` (`--threads`, default `$SLURM_CPUS_PER_TASK`, else all cores). When the timeout runs out, the run is recorded as `timeout`. A Docker container is named so the launcher can `docker kill` it, because killing `docker run` alone leaves the container running in the VM. A dead Docker VM makes `docker run` hang rather than fail, which is what the timeout guards against. Do not write `${VAR}` in a command, since braces are placeholders; `$VAR` is expanded by the shell inside the container. The README's "Compatible containers" table must list every tool in `tools/`.

**The tool's own container** (`Dockerfile`, `container/skullstrip-bench`, `invoke build-image`). Ubuntu 24.04, plus Apptainer 1.5.4 from its official release `.deb` (non-setuid), plus the `uv.lock` environment without dev tools, plus the code and `tools/`. The `VERSION` file is the git commit, and goes into `plan.json` as `skullstrip_bench_version`. The entry point is `invoke --search-root /opt/skullstrip-bench "$@"`, run from the caller's working directory. Running the tasks from it means **nested Apptainer** (the tool's container launches the tools' containers), which needs unprivileged user namespaces on the host. Rules that keep this working:
- data folders are bound at the **same path** inside, so plan paths hold on both sides;
- `tools/` is resolved from `PROJECT_DIR` (tasks.py's folder), never from the working directory;
- `SKULLSTRIP_BENCH_IN_CONTAINER=1` tells `slurm.py` to call `apptainer exec --bind … $APPTAINER_CONTAINER skullstrip-bench` in the job scripts, instead of this checkout's invoke;
- the tool's own image never goes in `--containers`.

Usage examples for clusters (building the `.sif` files from Docker Hub digests on a login node, a one-job test on a compute node, generating and submitting the array) live in the README, section "Running with Apptainer and Slurm". They are not versioned as `.sh` files: the user does not want example scripts in the repository.

**Build every download over https.** The dev Mac's institutional network stalls plain-http Ubuntu mirrors: 0 bytes in 60 s, while https answers in 1–3 s. The first build hung for over 20 minutes on `apt-get update`. The Dockerfile therefore switches apt sources to https, copies CA certificates from `buildpack-deps:noble-curl` (the base image has none), and fetches Apptainer's `.deb` with `ADD https://…`. Do not reintroduce `add-apt-repository` or `http://` sources. Typical build: about 3.5 min; image about 300 MB.

**Running on a cluster: `run --scheduler slurm`** (`analysis/slurm.py`) runs only the check, then writes to `.skullstrip-bench/slurm/`: `jobs.txt` (one participant per line, `sub-XX`), `skullstrip_array.sh` (array task N = participant on line N, every tool in sequence, then `run-update` adds that participant to metrics and report), `skullstrip_report.sh` (`run-aggregate`: full rebuild, provenance) and `submit.sh` (chains the report with `--dependency=afterany`, and refuses while `--account` is still `def-CHANGEME`). `--slurm-account` and `--slurm-array` fill in `--account` and `--array` at generation, or the user edits them (how many participants: a pilot `1-20`, all `1-N`, throttled `1-N%50`). Array resources: max `cpus`/`mem_gb` of the selected tools; walltime = (sum of per-tool minutes × the most T1w any participant has) × 1.5 + 10 min, rounded up to 15 min, where measured Apptainer durations in `<output>/runs/` replace the YAML `minutes`. In slurm mode the engine is always Apptainer, and every `.sif` must already exist (`prepare-images`, on a login node): array tasks must never build images concurrently. Tasks work on `$SLURM_TMPDIR` (`--work-root`) so only masks, logs and records reach the shared filesystem.

**Tool-specific notes.**
- SynthSeg outputs a segmentation: `labels_to_mask` (`analysis/postprocess.py`) keeps label > 0, CSF included as in SynthStrip's default, then resamples it nearest-neighbour onto the T1w grid.
- ANTs (`antsBrainExtraction.sh`) needs three files of the OASIS template (`ants.yaml`, `requires:`), bundled in `container_requirements/ants/`.
- Under Docker on Apple Silicon, SynthSeg (TensorFlow) needs more than 8 GB in the Docker VM. With 8 GB the VM crashed outright, and `docker run` then hangs instead of failing: give Docker 12 GB and enable Rosetta emulation.

**BIDS parsing is a small hand-written parser** (`analysis/bids_inputs.py`, adapted from wonkyconn), not pybids. A T1w's `stem` (its filename without `_T1w.nii.gz`) keeps every entity, so derivative names stay unique across sessions, runs and acquisitions. Subjects without a T1w are reported and skipped, not an error.

**Chunk concepts: one run = one (T1w × tool); one cluster array task = one participant (all tools).** Selectors: `--subjects` and `--tools` (comma-separated). A run's JSON record (OUTPUT/runs/TOOL/STEM.json) is its "already done" marker. Failed runs are recorded and skipped too (a slow ANTs run that ran out of memory must not be relaunched on every `invoke run`); retry them with `run-skullstrip --retry-failed` or `clean-skullstrip --tools <name>`.

**Build order (validate each stage with the user before the next):** structure + `run-check` ✔ → `run-skullstrip` + smoke test ✔ → full run SynthStrip + BET (+ metrics) ✔ → HTML report ✔ → SynthSeg ✔ → ANTs ✔ → user-facing CLI + Slurm mode ✔ → cluster pilot (next).

## Status and next session

**On Narval (2026-10-09).** The user built the four tools' `.sif` files in the user's scratch test folder from the pinned Docker Hub digests.
- FSL's build was killed twice on the login node during the SIF compression; the sandbox-then-job route (see README) worked.
- Next on the cluster: send `skullstrip-bench_<version>.tar`, convert it, generate the scripts with a 2-participant pilot (fast tools), and submit. This is the first real test of nested Apptainer.

**Where things stand (2026-10-07).**
- All four tools work end to end under Docker on the dev Mac. The 2026-10-06 full run was 5 subjects × 4 tools: 20/20 runs `ok`. Measured under amd64 emulation, per T1w: BET ≈ 8 s, SynthStrip ≈ 17 s, SynthSeg 3–5 min, ANTs ≈ 6.5 min.
- The user-facing command line is in place:
  - flags `--bids`, `--containers`, `--output`, `--tools`, `--subjects`, `--engine`, `--scheduler`;
  - a shallow dataset check, and no `fetch` (nothing is ever downloaded);
  - tool requirements bundled in `container_requirements/<tool>/` (declared with `requires:`);
  - `{threads}`, and the Slurm mode.
- The Slurm mode was tested locally only: script generation, `bash -n`, the `submit.sh` guard, and a simulated array task under Docker with fake `SLURM_*` variables.
- The tool's own container exists (`Dockerfile`, `build-image`). The cluster usage examples are in the README.
- **Apptainer has run for real (2026-10-07)**, inside the tool's container, with Docker `--privileged` as the outer container: it built `synthstrip_1.8.sif` from the `.tar` and processed sub-10159 in 42 s. The mask was identical voxel for voxel to the Docker one (1483.5 mL).
  - Apptainer refuses an `APPTAINER_TMPDIR` on a path shared from the Mac ("no parent mount point"). Use a container-local or node-local folder.
- The report is incremental, with Good / Bad / Uncertain ratings.
- **Nested Apptainer (Apptainer in Apptainer, unprivileged) and Slurm have not run on a real cluster yet.**

**Local testing uses only the fast tools.** On the dev Mac, run SynthStrip and FSL BET only (`--tools synthstrip,fsl-bet`). Never launch SynthSeg or ANTs locally again: they are validated, and they are slow and memory-hungry under emulation. To test Slurm generation without `.sif` files, point `--containers` at a scratch folder of empty `<name>.sif` files: the check only tests that they exist.

**User's local paths (dev Mac):**
- dataset: `/Users/pierrebergeret/Documents/TRAVAIL_DOCTORAT/sample_ds30`;
- images: `/Users/pierrebergeret/Documents/TRAVAIL_DOCTORAT/containers/skullstrip`;
- old 4-tool results (old output layout): `/Users/pierrebergeret/Documents/TRAVAIL_DOCTORAT/skullstrip_bench_results_2026-10-06`.

**Next.**
1. **Cluster pilot with the tool's container**: build `skullstrip-bench.sif`, run the README's test job, then `--scheduler slurm --slurm-array 1-20` with the fast tools, then use `seff` for real memory and time.
   - First check that nested Apptainer works on the compute nodes. If it does not, fall back to a Python checkout on the cluster (`uv sync`).
   - Regenerate afterwards: the measured durations replace the YAML estimates.
2. If nested Apptainer works: try SynthSeg and ANTs on the pilot too.
3. **Report for large datasets.** One self-contained HTML is about 5 MB per participant with 4 tools, so it cannot scale to thousands. Paginate (e.g. 20–50 participants per page plus an index), and probably put suspicious cases first (implausible volume, low Dice, failures).
4. Possibly: `clean-skullstrip --subjects`, and a `--retry-failed` option in the generated array script.

**Lessons from the dev Mac (Docker Desktop).**
- Both Docker crashes on 2026-10-06 came from the **Mac's disk being full** ("no space left on device"; the Docker VM disk alone is about 37 GB). Check `df -h` before long runs.
- SynthSeg also needs the Docker VM raised from 8 to 12 GB.
- When the VM dies, Docker Desktop stays half alive and the icon does nothing: quit the app, kill the leftover `com.docker.backend` processes, then `open -a Docker`.
- Never click "Reset to factory defaults": it deletes every loaded image.

## Data

### Where data lives

> In this project, the inputs are not in `source_data/` (it stays empty): they are read in place from `--bids` and `--containers` (see **No fetch step**). The template's general guidance below still applies to what is committed and how outputs are tracked. Its parts about fetching and datalad do not apply here.

`source_data/` holds inputs and nothing else; `output_data/` holds what the
pipeline computed. Neither is a scratch directory — a file that is neither a
declared input nor a produced output does not belong in either.

Both folders are **gitignored by default**, and that default is the right one:
data has its own distribution channel (a URL, a datalad dataset, a shared
filesystem), and git is bad at large binaries in a way that cannot be undone —
a big file committed once stays in the history forever. Track an output only
when it is small, diffable, and genuinely useful to read in a pull request: a
metrics table, yes; a NIfTI volume or a multi-megabyte figure, no. When a
project does start tracking outputs, keep a **guard line** in the folder's
`.gitignore` for the file types that must never be committed there, even if
nothing currently produces them:

```gitignore
# Guard: no step writes NIfTI here, but keep this so a stray volume can never
# be committed by accident.
*.nii.gz
```

`invoke verify` enforces the same idea mechanically — it fails on a tracked
file over ~10 MB or of a known-binary type — but a guard line documents the
intent at the place someone would otherwise break it.

### Datalad datasets, and plain assets

`--source` symlinks or copies a plain file or folder and does **not** run
`datalad get`. Symlinking a datalad dataset exposes only content that is
already present — un-fetched files are broken symlinks. So for a real datalad
dataset use `airoh.datalad` instead of `fetch_data`, configured under
`datasets:` in `invoke.yaml` (either `{name: output_dir}` or `{name: {output_dir,
url, source}}`):

- `install_dataset(c, name, source=None)` — make the checkout available:
  symlink an existing checkout at `source` (dataset tree only, does not
  `datalad get`), or `datalad clone` from `url`. No-op if `output_dir` already
  exists.
- `get_data(c, name, path=None, recursive=False, strict=False)` — retrieve
  content (the whole dataset, or just `path`). Tolerant of partial failures by
  default; `--strict` raises instead (use in the smoke test).
- `update_dataset(c, name, strict=False)` — advance an installed dataset's pin
  via `datalad update --merge`, without pulling content.
- For a plain git submodule (not datalad-backed), use
  `airoh.acquisition.ensure_submodule` instead.

A project with its own analysis-specific prefetch step (e.g. "get every file
matching this glob that a `run-*` step reads") composes it from
`airoh.datalad.prefetch_pattern` plus `load_known_failures`/
`save_known_failures` rather than reimplementing the glob/skip/get/reclassify
loop — see the `airoh` API reference for the full signatures.

Three things bite projects working with real datalad superdatasets:

- **Subdatasets nest.** A derivative folder is often a subdataset inside
  another subdataset, and plain `git submodule update --init` cannot reach one:
  it only sees the top level. `airoh.datalad.install_subdataset` (`datalad get
  -n <path>` under the hood) installs the intermediate dataset and the nested
  one in a single call, without pulling content, and without touching large
  sibling subdatasets.
- **Retrieval is partial and must be tolerant.** Content on credentialed
  remotes fails per-file for anyone without access. A fetch that aborts on the
  first inaccessible file is useless to collaborators with partial access:
  warn, skip, and carry on with whatever is reachable — every `airoh.datalad`
  retrieval function does this by default. Fail loudly only in the smoke test
  (`strict=True`), where an empty result means the plumbing is broken.
- **The annex version matters.** A repository in annex v10 format is simply
  refused by an older `git-annex`, and the failure looks like "no content
  anywhere" rather than an error. Pin it as a declared project dependency (the
  `git-annex` PyPI package bundles a recent binary) instead of writing a README
  note nobody reads.

**Gathering assets is a separate job from reproducing results.** In the
template, `fetch` retrieves and `run` reads what is already on disk and never
pulls; in this project nothing is ever retrieved, the user gathers the inputs
beforehand. Either way, a `run` that quietly downloads on demand is slow in a
way nobody can diagnose, and hides the fact that a result was produced from
data that arrived halfway through. If a step finds its input missing, it should
say so — not fix it silently.

### Sensitive and restricted data

Never commit identifiable data, credentials, or anything under a data-use
agreement — not to this repository, not "temporarily". Git history is not
erasable in practice once pushed.

- Keep the gitignore-by-default posture for `source_data/`, and add a guard
  line for the formats that would carry identifiable content.
- Restricted content usually lives behind a credentialed remote. Retrieval will
  fail for some people by design; that is not a bug to work around.
- **Document the access requirements in `source_data/CONTENT.md`**: who can get
  this data, how, and what a person without access will see. A collaborator
  whose `fetch` came back empty otherwise cannot tell whether the pipeline is
  broken or they simply lack permission — and will file the wrong bug.
- Derived outputs inherit the sensitivity of their inputs. An aggregate table
  is usually fine to track; a per-participant one usually is not.

### Recording asset versions

`run-check` writes `<output>/MANIFEST.json` and `run` writes
`<output>/PROVENANCE.json` (see `airoh.provenance`; in the template, `fetch`
writes the manifest). Between them they record
what each input actually resolved to — including the commit of a symlinked
external checkout — and what produced the current outputs: the project's own
commit and dirty flag, the environment, the manifest consumed, and a checksum
per output file. Both are small and git-tracked.

`PROVENANCE.json` changes on every run. That is the record working, not churn to
suppress; do not try to make it stable.

**These records attest, they do not retrieve.** They can tell you that a result
came from commit `abc123` of an input dataset with an uncommitted working tree —
which is exactly the question "why do my numbers differ from the paper's" needs
answered — but they cannot bring that state back. Retrieval is datalad's job,
and when this repository is aggregated as a submodule into a larger paper
project, datalad is what pins it. The records are what you get when datalad is
not in play, which is most of the time during day-to-day analysis.

## Verification

`invoke verify` checks that the code, config, data and documentation still agree.
It runs a flat list of independent checks — task list versus README, dependency
files against each other, paths named in the docs, each data folder against its
`CONTENT.md`, config keys, tracked file sizes, provenance freshness, the linter —
and exits non-zero if any of them fails. Configure it under `verify:` in
`invoke.yaml`.

**Run it before committing.** Documentation drift is invisible: nothing breaks
when the README lists a task that no longer exists, or a docstring describes
behaviour that was removed two commits ago, so it accumulates until a reader is
actively misled. These checks are the mechanical floor under the instruction to
keep CLAUDE.md and README.md current.

`verify` is deliberately **not** part of `run`. Reproducing results must not
depend on documentation hygiene, and a pipeline that refuses to compute because
a path in the README moved is a pipeline people route around.

The checks are mechanical, so they cannot evaluate a claim like "this step never
pulls data" or "the default threshold is 30". The `/verify` skill covers that
second layer: it runs these checks, then reads the prose against the code. Use
it after any change that alters what a step does, as opposed to what it is
called.

## Code style

**Module and function size:** Each module in `analysis/` covers a single concern; if a file grows past ~200 lines, consider splitting it. Each function should do one thing — aim for under ~30 lines; longer is a signal to extract a helper.

**Naming:** Prefer self-explanatory names over brevity: `n_subjects` not `n`, `output_path` not `p`, `group_means` not `gm`. Avoid abbreviations unless universally known in the domain (`df` for a DataFrame is fine).

**Linting:** flake8, configured in `setup.cfg` (max line length 100); run `uv run flake8` before committing. Never disable a lint rule without a comment explaining why.

**Testing:** Two baseline checks, and they cover different failures. `invoke run-smoke` is the behavioural one: does the pipeline run end to end and produce something. `invoke verify` is the structural one: do the code, config, data and docs still describe the same project. Run both before committing; neither substitutes for the other. Add unit tests in a tests directory, using the project's chosen test framework, when a function contains non-trivial logic, has edge cases the smoke test won't catch, or is shared across multiple steps. Unit tests are optional for simple glue/orchestration code but encouraged for any pure transformation or computation logic in `analysis/`. This project uses pytest, with tests in `tests/` (`uv run pytest`).

**Adding a new analysis step:** add a function to `analysis/`, add a `run-{name}` task and a matching `clean-{name}` task in `tasks.py`, call both from the bodies of the top-level `run` and `clean` tasks (see the `pre=` warning above — a body call, not `pre=`).

**Evolving CLAUDE.md:** Run `invoke verify` after any structural change — it catches the mechanical half of this instruction (renamed tasks, moved paths, undocumented outputs) that is otherwise left to memory. Keep this file current as the project grows. It should always reflect the actual scope of the project — what it does, what data it uses, and what analysis steps it contains. When adding or removing a task, rename a folder, or change the pipeline structure, update CLAUDE.md in the same commit. Stale guidance here misleads future AI sessions and collaborators alike.

**Keeping README.md current:** README.md is the user-facing documentation for this project. Any structural or workflow change — new tasks, renamed folders, updated commands, new dependencies — must be reflected there in the same commit. The task list in README.md should match `invoke --list` exactly; if a task is added or removed, update README.md accordingly. For data folder contents, point to `source_data/CONTENT.md` and `output_data/CONTENT.md` rather than duplicating their content inline.
