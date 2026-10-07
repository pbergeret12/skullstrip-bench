"""
Validation of a tool's mask, right after its run: the mask must exist, be
binary, and sit on the same grid as the T1w it was computed from.

There is deliberately no check of the T1w images themselves: `run-check` stays
shallow (folder layout only), and a broken T1w just fails its own run.
"""
import nibabel as nib
import numpy as np


def check_mask(mask_path, t1w_path):
    """
    The first thing wrong with a tool's mask, or None if it is usable: it must
    exist, be binary, and sit on the same grid (shape and affine) as the T1w.
    """
    try:
        mask = nib.load(mask_path)
    except FileNotFoundError:
        return "the tool produced no mask"
    t1w = nib.load(t1w_path)
    if mask.shape != t1w.shape or not np.allclose(mask.affine, t1w.affine, atol=1e-3):
        return f"mask grid {mask.shape} does not match the T1w grid {t1w.shape}"
    values = np.unique(np.asanyarray(mask.dataobj))
    if not set(values.tolist()) <= {0, 1}:
        return f"mask is not binary (values include {values[:5].tolist()})"
    if values.max(initial=0) == 0:
        return "mask is empty"
    return None
