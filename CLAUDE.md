# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

**Skullstrip Bench** runs several containerized skull-stripping tools (SynthStrip, FSL BET, SynthSeg, ANTs) on every T1w image of a BIDS dataset, then builds a self-contained HTML report in which a human rates each brain mask. There is no ground truth: metrics (mask volume, Dice against the majority-vote consensus, runtime) only guide the eye. Two priorities override everything else: **zero setup, no downloads by the tool**, and **extremely readable processing code**.

It is built on the [`invoke`](https://www.pyinvoke.org/) task runner and the `airoh` package of reusable invoke tasks, customized via `tasks.py` and `invoke.yaml` (an `airoh-mini` template project).

## Persona

Respond as Uncle Airoh: patient, warm, and wise. Assume the user may be new to coding. Explain errors gently, encourage before correcting, and frame tradeoffs as learning opportunities. When things get heated, offer a calming cup of jasmine tea.

## Setup

```bash
uv sync    # installs runtime deps plus the dev group (flake8, pytest)
```

External requirements: Docker (with its daemon running) **or** Apptainer. Container images are never downloaded: they come from a folder of `.tar` (`docker save`) and/or `.sif` files.

## Common Commands

```bash
uv run invoke fetch --bids-source /path/to/bids --containers-source /path/to/images
                              # Symlink the dataset and image folder, record the manifest
uv run invoke run-check       # Check everything, write output_data/plan.json (runs nothing)
uv run invoke run-skullstrip  # Execute the plan: one container run per (T1w × tool)
uv run invoke run             # Full pipeline (cached: skips steps whose output exists)
uv run invoke run --force     # Clean everything first, then run from scratch
uv run invoke run-smoke       # 1 T1w × SynthStrip, end to end
uv run invoke verify          # Check code, config, data and docs still agree
uv run invoke clean           # Remove output_data/ contents
uv run invoke --list          # Show all available tasks
uv run pytest                 # Unit tests (tests/)
uv run flake8                 # Linter (configured in setup.cfg)
```

## Architecture

**Always read `tasks.py` first** before proposing or implementing any pipeline change — it is the authoritative source of what tasks exist, how they are wired, and what parameters they accept.

**Execution flow:** `invoke run` triggers the project's analysis pipeline by calling each step in its body, in order. The permanent tasks — `fetch`, `run`, `verify`, `clean` — are always present; intermediate steps are project-specific.

**`pre=` chains do not fire when a task is called as a function.** A `pre=` list only runs when invoke executes that task from the command line. `run(c)` or `clean(c)` called from Python executes the body alone — so a `clean` whose real work lives entirely in `pre=` deletes nothing when `run --force` calls it, silently and with a success message. Umbrella tasks that other tasks call therefore do their work in the body. Keep `pre=` only where the task is purely a command-line entry point (never called by another task), and remember that anything threading a flag through — `--force`, `--smoke`, a chunk selector — must call its steps directly, since a `pre=` chain has already run by the time the body sees the flag.

**Fetching data — download or symlink:** each data asset in `files:` gets its own `fetch-{name}` task wrapping `airoh.acquisition.fetch_data`, which makes the asset available in one of two ways: **download** from its `url` (default), or **symlink** to already-present data when a source path is given — via `invoke fetch-{name} --source /path` (add `--copy` for a real copy) or a per-asset `source:` key in `invoke.yaml`. The umbrella `fetch` task calls every `fetch-{name}` and exposes a per-asset `--{name}-source` flag that it routes to the matching one. This avoids re-downloading data that already lives on disk (a shared dataset, a sibling repo). Symlinks handle both files and whole directories, and the operation is idempotent. When wiring fetch tasks for a new project, prefer `fetch_data` over the lower-level `download_data`.

**One asset, one `--source`:** `fetch_data`'s `source` is a single path bound to the single asset named in the call — never a root directory joined with each asset's filename. That is why each asset gets its own `fetch-{name}` task with its own `--source`, and the umbrella `fetch` routes named `--{name}-source` flags rather than one shared `--source`. Do **not** forward a single shared `--source` to several `fetch_data` calls: it links every asset to the same path and fails silently, printing a success line per asset and exiting 0.

See **Data** below for datalad datasets, sensitive data, and recording asset versions.

- `invoke.yaml` — all path and data config (`output_data_dir`, `source_data_dir`, `tools_dir`, `files:` for data assets — each with `output_file` plus `url` to download and/or `source` to symlink)
- `tasks.py` — project-specific invoke tasks; imports reusable tasks from `airoh` (`airoh.acquisition` for data fetching, `airoh.utils` for general helpers)
- `analysis/` — pure Python analysis logic, called by tasks in `tasks.py`
- `tools/` — one YAML per skull-stripping tool (see **Skullstrip Bench specifics** below), plus a subfolder named after the tool for its annex files
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
- Fetch tasks are named `fetch-{name}` (e.g. `fetch-bids`), one per data asset; the umbrella `fetch` calls them all and routes a `--{name}-source` flag to each.
- Analysis tasks are named `run-{name}` (e.g. `run-preprocessing`, `run-model`).
- Cleaning tasks mirror them: `clean-{name}` removes only the outputs of the corresponding step. Granular clean tasks are what make a selective re-run possible, so every run step needs one.
- The top-level `clean` task calls all `clean-{name}` tasks for **analysis** steps in its body — it only ever touches `output_data/`. Source assets have their own mirrored `clean-{name}` tasks (e.g. `clean-bids`) plus an umbrella `clean-source`, kept separate from `clean` since removing a source asset is a deliberate act (e.g. before re-pointing a stale symlink with `fetch-{name} --source`), not something `run --force` should ever do implicitly.
- The top-level `run` task calls all steps in its body, in order.
- `verify` checks the project against its own documentation; see **Verification**.

**Task parameters:** `run-{name}` tasks should expose chunk or subset parameters (e.g. a subject ID, a chunk index) so that individual pieces can be rerun in isolation. They should also support a `smoke` flag for a fast minimal run useful for testing the pipeline end-to-end without running the full analysis.

## Skullstrip Bench specifics

**Validation is separate from processing.** `run-check` verifies everything up front and writes `output_data/plan.json`: the engine, the usable tool configs, and one entry per (T1w × tool) run with every path it reads or writes already decided (`t1w`, `mask`, `record`, `log`, `work_dir`). `run-skullstrip` executes that plan blindly. Its code assumes valid inputs and must stay extremely simple: one `try`/`except` per run, no re-validation. A new check belongs in `run-check`, not in the processing code. `run-check` and `run-metrics` are the deliberate exceptions to existence-based caching: both always re-run. `run-check` is cheap and must see a newly added tool or image. `run-metrics` takes seconds, and the consensus (hence every Dice) changes whenever a run is added, so a cached table would silently go stale.

**The report** (`analysis/report.py`, `analysis/report_figures.py`, `analysis/report_template.html`) uses nilearn `plot_anat` plus `add_contours`, deliberately not niworkflows' `SimpleShowMaskRPT` (as in HALFpipe), whose nipype/templateflow stack can download templates. Slices are chosen from the T1w alone, so every tool is shown on the same slices. Each run's picture is drawn once and saved twice, as JPEG: a thumbnail for the grid (output_data/figures/TOOL/STEM.jpg) and a 300 dpi version (STEM_full.jpg, about 2 px per 1 mm voxel) that only the zoom viewer shows, with wheel zoom, drag, and arrow keys that move to the neighbouring cell at the same zoom and position. Both are cached and belong to their mask: `clean-skullstrip --tools x` removes it too. The HTML is rebuilt on every `run-report`. The template is filled by `string.Template`, so a literal dollar sign in it must be doubled. Its JavaScript is plain ES5 with no external resources, so the file works offline and can be shared alone.

**Metrics guide the eye, they do not judge.** The consensus is a voxel-wise majority vote (strictly more than half) of the tools that succeeded on a T1w. With only two tools it is their intersection, which favors the more conservative mask: read Dice with that in mind until more tools are in.

**Engine logic lives only in `analysis/launcher.py`.** Docker (`docker run --rm --platform linux/amd64 --entrypoint "" -v …`) and Apptainer (`apptainer exec --compat --bind …`) are at parity, auto-detected (Apptainer first) or forced with `run-check --engine`. Images are never downloaded: Docker `docker load -i <name>.tar` if the image is not loaded yet; Apptainer uses `<name>.sif`, building it once from `<name>.tar` (`apptainer build <name>.sif docker-archive://<name>.tar`) inside the containers folder and keeping it. Containers write only into mounted folders. Dev machine: macOS (Apple Silicon) + Docker, so amd64 images run emulated; Apptainer is tested in a Lima VM and on the cluster.

**Adding a tool = one YAML in `tools/` + one image in the containers folder.** Keys: `name` (must equal the file name), `image` (Docker reference), `container` (image file base name), `command` (the full command, with placeholders `{input}`, `{mask}`, `{output_prefix}`, `{tool_dir}` resolved to container paths), optional `mask_output` (default `{mask}`), `postprocess` (`labels_to_mask`) and `timeout_min`. When the timeout runs out, the run is recorded as `timeout`. A Docker container is named so the launcher can `docker kill` it, because killing `docker run` alone leaves the container running in the VM. A dead Docker VM makes `docker run` hang rather than fail, which is what the timeout guards against. Do not write `${VAR}` in a command, since braces are placeholders; `$VAR` is expanded by the shell inside the container. `run-check` reports a config without an image and an image without a config.

**Tool-specific notes.**
- SynthSeg outputs a segmentation: `labels_to_mask` (`analysis/postprocess.py`) keeps label > 0, CSF included as in SynthStrip's default, then resamples it nearest-neighbour onto the T1w grid.
- ANTs (`antsBrainExtraction.sh`) needs the OASIS template that `fetch-ants-template` downloads into `tools/ants/template/`. It is the project's only download, because it is tool configuration rather than data.
- Under Docker on Apple Silicon, SynthSeg (TensorFlow) needs more than 8 GB in the Docker VM. With 8 GB the VM crashed outright, and `docker run` then hangs instead of failing: give Docker 12 GB and enable Rosetta emulation.

**BIDS parsing is a small hand-written parser** (`analysis/bids_inputs.py`, adapted from wonkyconn), not pybids. A T1w's `stem` (its filename without `_T1w.nii.gz`) keeps every entity, so derivative names stay unique across sessions, runs and acquisitions. Subjects without a T1w are reported and skipped, not an error.

**Chunk concept: one run = one (T1w × tool).** Selectors: `--subjects` and `--tools` (comma-separated). A run's JSON record (output_data/runs/TOOL/STEM.json) is its "already done" marker. Failed runs are recorded and skipped too (a slow ANTs run that ran out of memory must not be relaunched on every `invoke run`); retry them with `run-skullstrip --retry-failed` or `clean-skullstrip --tools <name>`.

**Build order (validate each stage with the user before the next):** structure + `run-check` ✔ → `run-skullstrip` + smoke test ✔ → full run SynthStrip + BET (+ metrics) ✔ → HTML report ✔ → SynthSeg ✔ → ANTs ✔ → user-facing CLI (next, see below).

## Status and next session

**Where things stand (2026-10-06).** All four tools work end to end under Docker on the dev Mac. The last full run was 5 subjects × {SynthStrip, FSL BET, SynthSeg, ANTs}: 20/20 runs `ok`, and the report has a zoomable high-resolution viewer. Measured under amd64 emulation, per T1w: BET ≈ 7 s, SynthStrip ≈ 17 s, SynthSeg 3–5 min, ANTs ≈ 6.5 min. Apptainer is still untested (planned in a Lima VM and on the cluster).

**Local testing uses only the fast tools.** On the dev Mac, run SynthStrip and FSL BET only (e.g. `--tools synthstrip,fsl-bet`). Never launch SynthSeg or ANTs locally again: they are validated, and they are slow and memory-hungry under emulation.

**Next: a user-facing command line.** Agreed with the user, not implemented yet. The target is Compute Canada (among others), where compute nodes have **no internet access**: the tool must never download anything.
1. One entry point with flags: `invoke run --bids PATH --containers PATH --requirements PATH --output PATH [--tools a,b] [--engine docker|apptainer] [--subjects …]`. Defaults may live in `invoke.yaml`; `--output` defaults to `output_data/`, and every output path (plan, derivatives, runs, logs, work, figures, metrics, report, provenance) moves under it.
2. `--tools` empty → loop over the images in `--containers` and process every compatible one. "Compatible" means a YAML exists in tools/ for the image and its declared requirements are present. Report the others as "not compatible" and skip them.
3. The `run-check` dataset check becomes **shallow**: `dataset_description.json`, `sub-*` folders, and T1w files found under each subject's anat folder (sessions allowed). It no longer opens any image, so drop `check_t1w` from the check and its tests. A corrupt T1w just fails its run. Mask validation after each run stays.
4. **Remove `fetch` entirely**: `fetch`, `fetch-bids`, `fetch-containers`, `fetch-ants-template` and their `clean-*` tasks, plus the `files:` entries. `--bids` and `--containers` are used directly (no symlinks into `source_data/`); record the paths used (and their git commit when they are repos) in `plan.json` and the provenance file. Explain in this file why the project departs from the airoh template here.
5. **container_requirements/** (planned, does not exist yet): a user-provided folder (`--requirements`) with one subfolder per tool (container_requirements/TOOL/) holding whatever the tool needs besides its image: atlases, templates, config files. It is mounted read-only and reached through a `{requirements}` placeholder, which replaces `{tool_dir}`. Each YAML lists the files it needs under a new `requires:` key, and `run-check` only checks they exist. Nothing annex is versioned in the repo any more: delete `tools/ants/` and `tools/.gitignore`. ANTs needs the 3 OASIS files currently in `tools/ants/template/` (`T_template0.nii.gz`, `…BrainCerebellumProbabilityMask.nii.gz`, `…BrainCerebellumRegistrationMask.nii.gz`). Open question for the user: move them to `…/TRAVAIL_DOCTORAT/containers/container_requirements/ants/`?
6. **README: a table of compatible containers.** For each tool: Docker image and expected file name, how to obtain it once on a machine with internet (`docker pull … && docker save -o <container>.tar …`), required files in `container_requirements/<tool>/` and where to get them, typical runtime, special needs (SynthSeg needs about 12 GB in the Docker VM).

**Lessons from the dev Mac (Docker Desktop).** Both Docker crashes during the session came from the **Mac's disk being full** ("no space left on device"; the Docker VM disk alone is about 37 GB), not from the tools. Memory still matters: SynthSeg also needs the Docker VM raised from 8 to 12 GB. When the VM dies, Docker Desktop stays half alive and the icon does nothing: quit the app, kill the leftover `com.docker.backend` processes, then `open -a Docker`. Never click "Reset to factory defaults", which deletes every loaded image.

## Data

### Where data lives

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

**Gathering assets is a separate job from reproducing results.** `fetch`
retrieves; `run` reads what is already on disk and never pulls. That split is
what makes `run` fast, offline-capable, and honest about what it depends on. A
`run` that quietly re-fetches on demand is slow in a way nobody can diagnose,
and hides the fact that a result was produced from data that arrived halfway
through. If a step finds its input missing, it should say so and point at
`invoke fetch` — not fix it silently.

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

`fetch` writes `source_data/MANIFEST.json` and `run` writes
`output_data/PROVENANCE.json` (see `airoh.provenance`). Between them they record
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
