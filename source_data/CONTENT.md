# 📁 Source Data Contents

Nothing here is downloaded. After `invoke fetch`, expect:

- `bids` — a symlink to the BIDS dataset to benchmark (made by `invoke fetch-bids --source /path`).
  Only its dataset_description.json and the T1w images (sub-X/[ses-Y/]anat/*_T1w.nii.gz) are read.
  Test dataset: 5 subjects of OpenNeuro ds000030 (public, de-identified).
- `containers` — a symlink to the folder of container images (made by
  `invoke fetch-containers --source /path`). It holds only images: Docker archives
  `<name>.tar` (from `docker save`) and/or Apptainer `<name>.sif` files, with no
  configuration (that lives in `tools/`). With Apptainer, a missing `.sif` is built once from its
  `.tar` and kept in the real folder, through the link.
- `MANIFEST.json` — what each asset resolved to (the real path behind each link),
  written by `invoke fetch`. Tracked in git.

📝 Access: this project ships no data. Whoever runs it must already have a BIDS
dataset and the container images on disk. When it runs on a restricted dataset,
that dataset's own access rules apply, and nothing derived from it should be
committed (see `.gitignore` here and in `output_data/`).

📝 Both entries are links: `invoke clean-bids` / `clean-containers` remove the
link, never the data it points to. `fetch` never overwrites an existing link, so
clean first to re-point one.
