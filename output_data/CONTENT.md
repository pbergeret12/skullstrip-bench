# 📁 Output Data Contents

This is the default output folder (`--output`). Any other output folder gets
the same layout. Once the pipeline has run, it contains:

- `plan.json` — written by `invoke run-check`: the input paths, the engine,
  the scheduler, the participants, the usable tool configs, and one entry per
  (T1w × tool) run with every path it reads or writes. `run-skullstrip`
  executes it.
- `MANIFEST.json` — written by `invoke run-check`: what each input path
  (`--bids`, `--containers`, `--requirements`) resolved to, with its git commit
  when it is a repository. Tracked in git here.
- `derivatives/` — BIDS derivatives, one dataset per tool (with its own
  dataset_description.json): derivatives/TOOL/sub-X/[ses-Y/]anat/STEM_desc-brain_mask.nii.gz.
  Written by `run-skullstrip`, only for runs whose mask passed validation.
- `runs/` — one JSON record per run (status `ok` / `failed` / `oom` / `timeout`,
  duration, exit code, error, engine, image). Also the run's "already done"
  marker, and the source of measured durations for Slurm walltimes.
- `logs/` — per run: the full engine command line, then everything the container printed.
- `work/` — the folder mounted as /output in each run's container; the tool's
  raw outputs stay here for debugging (SynthSeg's segmentation, ANTs' outputs, and
  mask_postprocessed.nii.gz for tools with a post-processing step). On a
  cluster, runs work on the node's local disk instead, and nothing lands here.
- `figures/` — two pictures per successful run, the T1w with the mask's outline in
  red: figures/TOOL/STEM.jpg (thumbnail for the grid) and STEM_full.jpg (high
  resolution, for the zoom viewer). Drawn by `invoke run-figures` and cached.
- `metrics.csv` — written by `invoke run-metrics`, one row per run: subject,
  stem, tool, status, volume_ml, dice_consensus (against the majority vote of the
  tools that succeeded on that T1w; empty with fewer than two), n_tools_consensus,
  duration_s, error.
- `report.html` — the self-contained visual report (images embedded), rebuilt by
  every `invoke run-report`. Open it in a browser to rate each mask.
- `slurm/` — only with `--scheduler slurm`: jobs.txt (one participant per line),
  skullstrip_array.sh, skullstrip_report.sh, submit.sh, and logs/ for the
  jobs' output.
- `PROVENANCE.json` — what produced everything here: project commit,
  environment, the input manifest, a checksum per output. Written by `invoke run`
  (or the cluster report job). Tracked in git and changes on every run, by design.

📝 Everything except `PROVENANCE.json` and `MANIFEST.json` is ignored by git:
masks and the report show participants' brains, and the metrics are
per-participant data.
