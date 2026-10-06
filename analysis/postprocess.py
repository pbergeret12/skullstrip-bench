"""
Turn a tool's raw output into a brain mask on the T1w grid, for tools that do
not write one directly (named by `postprocess:` in the tool's YAML).
"""
import nibabel as nib
import numpy as np
from nilearn.image import new_img_like, resample_to_img


def labels_to_mask(output_file, t1w_file, mask_file):
    """
    Segmentation → mask: every labelled voxel (label > 0, CSF included) is
    brain, then nearest-neighbour resampling onto the T1w grid — SynthSeg, for
    one, segments at 1 mm whatever the input resolution.
    """
    segmentation = nib.load(output_file)
    labelled = new_img_like(segmentation, (np.asanyarray(segmentation.dataobj) > 0)
                            .astype(np.uint8))
    on_t1w_grid = resample_to_img(labelled, nib.load(t1w_file), interpolation="nearest",
                                  force_resample=True, copy_header=True)
    mask = np.asanyarray(on_t1w_grid.dataobj).astype(np.uint8)
    nib.save(nib.Nifti1Image(mask, on_t1w_grid.affine), mask_file)
    return mask_file


POSTPROCESSES = {"labels_to_mask": labels_to_mask}
