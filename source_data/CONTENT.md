# 📁 Source Data Contents

Empty on purpose. Skullstrip Bench downloads nothing and copies nothing in:
its inputs are read where they already are, given as flags to `invoke run`
(or as defaults under `inputs:` in `invoke.yaml`):

- `--bids` — the BIDS dataset. Only its dataset_description.json and the T1w
  images (sub-X/[ses-Y/]anat/*_T1w.nii.gz) are read.
- `--containers` — a folder holding only container images: Docker archives
  `<name>.tar` (from `docker save`) and/or Apptainer `<name>.sif` files.
- `--requirements` — a folder with one subfolder per tool holding the files
  that tool needs besides its image (atlases, templates, configs).

What each input resolved to is recorded in the output folder's MANIFEST.json
(see `output_data/CONTENT.md`).

📝 Access: this project ships no data. Whoever runs it must already have the
dataset, the images and the requirements on disk. On a restricted dataset, its
own access rules apply, and nothing derived from it should be committed.
