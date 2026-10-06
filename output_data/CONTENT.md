# 📁 Output Data Contents

Once the pipeline has run, this folder contains:

- `plan.json` — written by `invoke run-check`: the engine, the usable tool
  configs, and one entry per (T1w × tool) run with every path it reads or writes.
  `run-skullstrip` executes it.
- `derivatives/` — BIDS derivatives, one dataset per tool (with its own
  dataset_description.json): derivatives/TOOL/sub-X/[ses-Y/]anat/STEM_desc-brain_mask.nii.gz.
  Written by `run-skullstrip`, only for runs whose mask passed validation.
- `runs/` — one JSON record per run (status `ok` / `failed` / `oom` / `timeout`, duration,
  exit code, error, engine, image). Also the run's "already done" marker.
- `logs/` — per run: the full engine command line, then everything the container printed.
- `work/` — the folder mounted as /output in each run's container; the tool's
  raw outputs stay here for debugging (SynthSeg's segmentation, ANTs' outputs, and
  mask_postprocessed.nii.gz for tools with a post-processing step).
- `PROVENANCE.json` — what produced everything here: project commit,
  environment, the input manifest, a checksum per output. Written by `invoke run`.
  Tracked in git and changes on every run, by design.

- `metrics.csv` — written by `invoke run-metrics`, one row per run: subject,
  stem, tool, status, volume_ml, dice_consensus (against the majority vote of the
  tools that succeeded on that T1w; empty with fewer than two), n_tools_consensus,
  duration_s, error.

- `figures/` — two pictures per successful run, the T1w with the mask's outline in
  red: figures/TOOL/STEM.jpg (thumbnail for the grid) and STEM_full.jpg (high
  resolution, for the zoom viewer). Drawn by `invoke run-report` and cached.
- `report.html` — the self-contained visual report (images embedded), rebuilt by
  every `invoke run-report`. Open it in a browser to rate each mask.

📝 Everything except `PROVENANCE.json` is ignored by git: masks and the report
show participants' brains, and the metrics are per-participant data.
