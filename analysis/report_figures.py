"""
One picture per run for the report: the T1w with the mask's outline in red,
in axial, coronal and sagittal views, several slices each.

Drawn once, saved twice: a small thumbnail for the grid, and a large version
that only the zoom view shows, to check the outline voxel by voxel.

The slices are chosen from the T1w alone, so every tool is shown on exactly
the same slices of a given T1w — differences between columns are differences
between masks.
"""
import matplotlib

matplotlib.use("Agg")  # no screen needed

import matplotlib.pyplot as plt  # noqa: E402  (must come after matplotlib.use)
import nibabel as nib  # noqa: E402
import numpy as np  # noqa: E402
from nilearn import plotting  # noqa: E402

VIEWS = (("z", "axial"), ("y", "coronal"), ("x", "sagittal"))
N_SLICES = 5
FIGURE_SIZE_INCHES = (10, 6)
THUMBNAIL_DPI = 90     # 900 × 540 px in the grid
FULL_DPI = 300         # 3000 × 1800 px when zoomed: about 2 px per 1 mm voxel
CONTOUR_WIDTH = 0.35   # points: a thin line at full size, still visible as a thumbnail
JPEG_QUALITY = 90
# Percentile range of the head covered by the slices, per axis: the axial
# range starts higher, to skip the neck.
SLICE_RANGES = {"x": (15, 85), "y": (15, 85), "z": (30, 85)}


def slice_positions(t1w_path, n_slices=N_SLICES):
    """
    World coordinates of `n_slices` slices per axis, spread over the head.

    The head is roughly "voxels brighter than the mean"; slices are spread over
    the percentile range of SLICE_RANGES along each axis.
    """
    image = nib.load(t1w_path)
    data = np.asanyarray(image.dataobj)
    head_voxels = np.argwhere(data > data.mean())
    head_coords = nib.affines.apply_affine(image.affine, head_voxels)
    return {axis: np.percentile(head_coords[:, index],
                                np.linspace(*SLICE_RANGES[axis], n_slices)).round(1).tolist()
            for index, axis in enumerate("xyz")}


def draw_mask_outline(t1w_path, mask_path, thumbnail_file, full_file):
    """Save the T1w with the mask's outline in red, one row per view, at two sizes."""
    cuts = slice_positions(t1w_path)
    figure = plt.figure(figsize=FIGURE_SIZE_INCHES, facecolor="black")
    for row, (axis, _) in enumerate(VIEWS):
        axes = figure.add_axes([0, 1 - (row + 1) / len(VIEWS), 1, 1 / len(VIEWS)])
        display = plotting.plot_anat(t1w_path, display_mode=axis, cut_coords=cuts[axis],
                                     axes=axes, annotate=False, black_bg=True, dim=0,
                                     colorbar=False)
        display.add_contours(mask_path, levels=[0.5], colors="red", linewidths=CONTOUR_WIDTH)
    thumbnail_file.parent.mkdir(parents=True, exist_ok=True)
    for output_file, dpi in ((thumbnail_file, THUMBNAIL_DPI), (full_file, FULL_DPI)):
        figure.savefig(output_file, dpi=dpi, facecolor="black",
                       pil_kwargs={"quality": JPEG_QUALITY})
    plt.close(figure)
