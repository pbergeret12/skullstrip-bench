# Skullstrip Bench

_why don't you have a cup of relaxing jasmine tea?_

Skullstrip Bench runs several containerized skull-stripping tools (SynthStrip, FSL BET, SynthSeg, ANTs) on every T1w image of a BIDS dataset, then builds a self-contained HTML report in which you rate each brain mask. There is no ground truth: the final call is yours, and the metrics (mask volume, Dice against the consensus of all tools, runtime) are only there to guide the eye.

Two goals drive the design: **no setup and no downloads** (the tool runs container images you already have), and **processing code that stays easy to read**.

Built on the [`invoke`](https://www.pyinvoke.org/) task runner and [`airoh`](https://pypi.org/project/airoh/) (from the `airoh-mini` template).

⚠️ **Status**: built stage by stage during BrainHack School. Working end to end with SynthStrip, FSL BET, SynthSeg and ANTs under Docker (Apptainer still to be tested). Next: a single command with `--bids`, `--containers`, `--requirements`, `--output` and `--tools` flags, without any download, so it runs on clusters without internet such as Compute Canada.

---

## ✨ TL;DR

```bash
uv sync
uv run invoke fetch --bids-source /path/to/bids --containers-source /path/to/images
uv run invoke run-check
uv run invoke run
```

---

## 🚀 Quick Start

### Step 1: Install

```bash
uv sync
```

This creates a `.venv` with the runtime dependencies plus the dev tools (`flake8`, `pytest`).

You also need a container engine: **Docker** (daemon running) or **Apptainer**. Apptainer is used if available, otherwise Docker. Force one with `invoke run-check --engine docker`.

### Step 2: Link your data

Nothing is ever downloaded. You point the project at two folders you already have:

- a **BIDS dataset** (with a dataset_description.json and T1w images in each subject's anat folder, sessions allowed);
- a **containers folder** holding only images: Docker archives (`<name>.tar`, made with `docker save`) and/or Apptainer `<name>.sif` files.

```bash
uv run invoke fetch --bids-source /path/to/bids --containers-source /path/to/images
uv run invoke fetch-bids --source /path/to/bids      # or one at a time
```

Both become symlinks in `source_data/`. `fetch` also downloads, once, the brain template ANTs needs (into `tools/ants/template/`): it is part of the tool's configuration, not data. To point at another dataset, remove the link first with `uv run invoke clean-bids` (or `clean-containers`, or `clean-source` for both); this removes the link, never your data.

### Step 3: Check, then run

```bash
uv run invoke run-check
```

`run-check` launches nothing. It checks the dataset (each T1w opens, is 3D, and has a plausible grid; subjects without a T1w are reported), the tool configs in `tools/` against the images in the containers folder, the engine, and the output folder. Then it prints a ✔/✘ summary and writes the run plan to `output_data/plan.json`. Restrict it with `--subjects 10159,10171` or `--tools synthstrip`.

```bash
uv run invoke run            # check → skullstrip → metrics → report
uv run invoke run --force    # clean everything, then run from scratch
```

Each (T1w × tool) run writes a BIDS-derivative mask, its container log, and a record of its status and duration. A run that fails (a tool error, out of memory, longer than the tool's `timeout_min`, or a mask that is missing, not binary, or off the T1w grid) is recorded and the next one starts.

Every step skips work whose output already exists, so `invoke run` is cheap to repeat. Failed runs count as done too, so a slow tool that crashed is not relaunched every time: retry with `uv run invoke run-skullstrip --retry-failed`, or `uv run invoke clean-skullstrip --tools fsl-bet` to redo one tool. The flip side: editing a script does **not** re-run anything. Use `invoke run --force`, or a `clean-{name}` task, to rebuild.

### Step 4: Judge the masks

Open **`output_data/report.html`** in a browser. It has one row per T1w and one column per tool. Each cell shows the T1w with the mask's outline in red, in axial, coronal and sagittal views (the same slices for every tool); click a picture to open its high-resolution version: zoom with the mouse wheel, drag to move, and use the arrow keys to switch to another tool (← →) or T1w (↑ ↓) **at the same zoom and position**. Under each picture:
- the mask volume, highlighted outside the plausible range set in `invoke.yaml` (`report: plausible_volume_ml`, 1100–1600 mL by default);
- the Dice against the consensus of the tools;
- the runtime.

A failed run shows its error instead. Rate each mask **OK / Fail / Doubtful**, add a comment, then use **Export notes (CSV)**. Notes are kept in your browser between reloads, but the CSV export is your real record.

The file is self-contained (images embedded), so you can send it as is. It shows participants' brains, though, so share it only where the dataset's rules allow.

### Step 5: Smoke test and consistency checks

```bash
uv run invoke run-smoke   # 1 T1w × SynthStrip, end to end
uv run invoke verify      # code, config, data and docs still agree
uv run pytest             # unit tests
uv run flake8             # linter
```

---

## 🧩 Adding a tool

One YAML in `tools/` plus one image in the containers folder:

```yaml
# tools/synthstrip.yaml
name: synthstrip                    # must match the file name
image: freesurfer/synthstrip:1.8    # Docker reference
container: synthstrip_1.8           # <containers>/synthstrip_1.8.tar or .sif
command: mri_synthstrip -i {input} -m {mask}
# mask_output: "{output_prefix}_mask.nii.gz"   # if the tool picks its own mask name
# postprocess: labels_to_mask                    # if the tool outputs a segmentation
# timeout_min: 30                                # stop a run stuck for 30 minutes
```

Placeholders `{input}`, `{mask}`, `{output_prefix}` and `{tool_dir}` are replaced by paths inside the container. Annex files such as templates go in a `tools/` subfolder named after the tool, mounted as `{tool_dir}`.

---

## 🧰 Task Overview

| Task               | Description |
| ------------------ | ----------- |
| `fetch`            | Links all source data; routes `--bids-source` / `--containers-source` to the tasks below |
| `fetch-bids`       | Symlinks (or `--copy`) a BIDS dataset to `source_data/bids` |
| `fetch-ants-template` | Downloads the OASIS template used by ANTs into `tools/ants/template/` (the project's only download: tool configuration, not data) |
| `fetch-containers` | Symlinks (or `--copy`) the folder of container images to `source_data/containers` |
| `run-check`        | Checks everything without running anything and writes `output_data/plan.json`; always re-runs |
| `run-skullstrip`   | Executes the plan, one container run per (T1w × tool); `--subjects`, `--tools`, `--retry-failed` |
| `run-metrics`      | Writes `output_data/metrics.csv`: volume, Dice against the consensus, duration and status per run; always re-runs |
| `run-report`       | Writes `output_data/report.html`: masks drawn on the T1w, metrics, rating buttons and CSV export; pictures are cached, the HTML is always rebuilt |
| `run`              | Full pipeline (all `run-{name}` steps in order); `--force` cleans first |
| `run-smoke`        | Fast end-to-end pass: 1 T1w × SynthStrip |
| `verify`           | Checks that code, config, data and docs still agree |
| `clean`            | Removes all computed outputs |
| `clean-check`      | Removes `output_data/plan.json` |
| `clean-skullstrip` | Removes masks, run records, logs, work folders and their report pictures; `--tools` limits it to some tools |
| `clean-metrics`    | Removes `output_data/metrics.csv` |
| `clean-report`     | Removes the report and its cached pictures |
| `clean-source`     | Removes both source links (calls `clean-bids` and `clean-containers`) |
| `clean-ants-template` | Removes the downloaded ANTs template |
| `clean-bids`       | Removes the `source_data/bids` link |
| `clean-containers` | Removes the `source_data/containers` link |

Use `uv run invoke --list` or `uv run invoke --help <task>` for details.

---

## 📁 Folder Structure

| Folder / File  | Description |
| -------------- | ----------- |
| `analysis/`    | Processing code called by the tasks: BIDS parsing, image checks, tool configs, the container launcher (the only engine-aware module), the checks |
| `tools/`       | One YAML per skull-stripping tool |
| `tests/`       | pytest unit tests |
| `source_data/` | Links to the inputs; see [`source_data/CONTENT.md`](source_data/CONTENT.md) |
| `output_data/` | Plan, masks, logs, metrics and report; see [`output_data/CONTENT.md`](output_data/CONTENT.md) |
| `tasks.py`     | The invoke tasks |
| `invoke.yaml`  | Config: paths and data assets |

---

## 🔒 Data

Masks, the report and per-run metrics show or describe participants' brains, so everything under `output_data/` stays out of git (only `PROVENANCE.json` is tracked). The same goes for `source_data/` (only `MANIFEST.json`). Keep it that way when running on restricted datasets.

---

## Philosophy

Inspired by Uncle Iroh from *Avatar: The Last Airbender*, `airoh` aims to bring simplicity, reusability, and clarity to research infrastructure — one well-structured task at a time.

When working in this project, Claude Code responds as **Uncle Airoh**: patient, warm, and wise.
