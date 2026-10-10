"""
`--reconall`: show what HALFpipe makes of a tool's mask once FreeSurfer has run.

With `run_reconall: true`, HALFpipe's fMRIPrep does not keep the skull
stripping's mask: after recon-all it rebuilds the mask from FreeSurfer's
segmentation (sMRIPrep's mask refinement). `--reconall synthseg,ants` adds a
run per T1w for each named tool, shown as its own column (`synthseg+reconall`):
the T1w stripped with that tool's mask goes through fMRIPrep, anatomy only,
skull stripping `skip` and recon-all on, from HALFpipe's own image, exactly as
a pre-stripped T1w does in the HALFpipe pipeline. Its mask is fMRIPrep's
final `desc-brain_mask`.

The refining config is `tools/reconall.yaml` (`refines_masks: true`).
FreeSurfer needs a license, which cannot ship with this public project: the
user puts `license.txt` next to the images, in the containers folder.
"""
import json
from pathlib import Path

import nibabel as nib
import numpy as np

from analysis.launcher import image_status

LICENSE_FILE = "license.txt"
SUFFIX = "+reconall"
PARTICIPANT = "01"   # the one participant of the small BIDS dataset given to fMRIPrep


def refined_name(base_tool):
    return f"{base_tool}{SUFFIX}"


def check_reconall(bases, refiner, usable_tools, engine, containers_dir, require_sif, report):
    """
    Check `--reconall`, return the refined variants to add to the plan's tools
    (`{"synthseg+reconall": {...config, "refines": "synthseg"}}`). `report`
    prints one ✔/✘ line.
    """
    print(f"\nRecon-all  (fMRIPrep from HALFpipe's image, license in {containers_dir})")
    if refiner is None:
        report(False, "no config with refines_masks: true in tools/ (reconall.yaml)")
        return {}
    ready, message = image_status(engine, refiner, containers_dir, require_sif)
    report(ready, f"{refiner['name']}: {message}")
    has_license = (Path(containers_dir) / LICENSE_FILE).is_file()
    report(has_license, f"FreeSurfer {LICENSE_FILE} "
           + ("found" if has_license else f"missing from {containers_dir}"))
    variants = {}
    for base in bases:
        if base not in usable_tools:
            report(False, f"{refined_name(base)}: {base} is not among the tools that run")
        elif ready and has_license:
            variants[refined_name(base)] = {**refiner, "refines": base}
            report(True, f"{refined_name(base)}: will refine {base}'s masks")
    return variants


def prepare_input(run, bids_dir):
    """
    Write the small BIDS dataset fMRIPrep reads: the T1w stripped with the
    base tool's mask, as `sub-01`. Fails if the base tool has no mask (its run
    failed): there is nothing to refine.
    """
    if not Path(run["base_mask"]).is_file():
        raise RuntimeError(f"no {run['refines']} mask to refine (its run failed or is missing)")
    t1w = nib.load(run["t1w"])
    mask = np.asanyarray(nib.load(run["base_mask"]).dataobj) > 0
    stripped = np.where(mask, np.asanyarray(t1w.dataobj), 0)
    anat_dir = Path(bids_dir) / f"sub-{PARTICIPANT}" / "anat"
    anat_dir.mkdir(parents=True)
    nib.save(nib.Nifti1Image(stripped, t1w.affine, t1w.header),
             anat_dir / f"sub-{PARTICIPANT}_T1w.nii.gz")
    (Path(bids_dir) / "dataset_description.json").write_text(
        json.dumps({"Name": "skullstrip-bench recon-all", "BIDSVersion": "1.8.0"}))
