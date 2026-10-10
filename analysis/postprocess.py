"""
Turn a tool's raw output into a brain mask on the T1w grid, for tools that do
not write one directly (named by `postprocess:` in the tool's YAML).
"""
from pathlib import Path

import nibabel as nib
import numpy as np
from nilearn.image import new_img_like, resample_to_img

SYNTHSEG_CSF = 24   # SynthSeg's label for the CSF around the brain


def labels_to_mask(output_file, t1w_file, mask_file, excluded_labels=()):
    """
    Segmentation → mask: every labelled voxel (label > 0) is brain, except the
    `excluded_labels`; then nearest-neighbour resampling onto the T1w grid
    (SynthSeg, for one, segments at 1 mm whatever the input resolution).
    """
    segmentation = nib.load(output_file)
    labels = np.asanyarray(segmentation.dataobj)
    brain = (labels > 0) & ~np.isin(labels, excluded_labels)
    return save_on_t1w_grid(new_img_like(segmentation, brain.astype(np.uint8)),
                            t1w_file, mask_file)


def synthseg_brain_mask(output_file, t1w_file, mask_file):
    """
    SynthSeg → mask as in our HALFpipe pipeline (its apply_mask.py): every
    label except the CSF around the brain (24).
    """
    return labels_to_mask(output_file, t1w_file, mask_file, excluded_labels=(SYNTHSEG_CSF,))


def fmriprep_brain_mask(fmriprep_dir, t1w_file, mask_file):
    """
    fMRIPrep's final brain mask (`*_desc-brain_mask.nii.gz` in anat/, in the
    T1w's own space, not a template's), put back on the original T1w grid:
    fMRIPrep reorients its anatomical reference.
    """
    found = sorted(path for path in Path(fmriprep_dir).rglob("*_desc-brain_mask.nii.gz")
                   if path.parent.name == "anat" and "space-" not in path.name)
    if not found:
        raise RuntimeError(f"fMRIPrep wrote no anatomical desc-brain_mask in {fmriprep_dir}")
    mask = nib.load(found[0])
    binary = (np.asanyarray(mask.dataobj) > 0).astype(np.uint8)
    return save_on_t1w_grid(new_img_like(mask, binary), t1w_file, mask_file)


def save_on_t1w_grid(binary_image, t1w_file, mask_file):
    """Nearest-neighbour resampling of a binary image onto the T1w grid, saved as uint8."""
    on_t1w_grid = resample_to_img(binary_image, nib.load(t1w_file), interpolation="nearest",
                                  force_resample=True, copy_header=True)
    mask = np.asanyarray(on_t1w_grid.dataobj).astype(np.uint8)
    nib.save(nib.Nifti1Image(mask, on_t1w_grid.affine), mask_file)
    return mask_file


POSTPROCESSES = {"labels_to_mask": labels_to_mask, "synthseg_brain_mask": synthseg_brain_mask,
                 "fmriprep_brain_mask": fmriprep_brain_mask}
