"""
Sanity checks on a T1w image, run by `run-check` before anything is launched.
"""
import nibabel as nib
import numpy as np

# Generous bounds: they catch a broken header, not an unusual protocol.
DIMENSION_RANGE = (32, 1024)
VOXEL_SIZE_RANGE_MM = (0.2, 5.0)


def check_t1w(path):
    """
    Return `(problem, summary)` for one T1w image.

    `problem` is None when the image is usable, else a short explanation.
    `summary` describes the grid, e.g. `256×256×176, 1.0×1.0×1.2 mm`.
    """
    try:
        image = nib.load(path)
        shape = image.shape
        affine = image.affine
    except Exception as error:  # any unreadable file, whatever nibabel raises
        return f"cannot be read ({error})", ""

    voxel_sizes = nib.affines.voxel_sizes(affine)
    summary = ("×".join(str(size) for size in shape) + ", "
               + "×".join(f"{size:.1f}" for size in voxel_sizes) + " mm")

    if len(shape) != 3:
        return f"is {len(shape)}D, expected 3D", summary
    if not np.all(np.isfinite(affine)) or np.isclose(np.linalg.det(affine[:3, :3]), 0):
        return "has an invalid affine", summary
    if not all(DIMENSION_RANGE[0] <= size <= DIMENSION_RANGE[1] for size in shape):
        return "has implausible dimensions", summary
    if not all(VOXEL_SIZE_RANGE_MM[0] <= size <= VOXEL_SIZE_RANGE_MM[1] for size in voxel_sizes):
        return "has implausible voxel sizes", summary
    return None, summary


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
