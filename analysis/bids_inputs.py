"""
Find the T1w images of a BIDS dataset.

A deliberately small parser instead of pybids: we only need the anatomical T1w
files and their entities, and reading BIDS filenames is simple enough to do by
hand. `split_ext` and `parse` are adapted from wonkyconn
(https://github.com/SIMEXP/wonkyconn, wonkyconn/file_index/bids.py).
"""
from pathlib import Path

T1W_GLOBS = ("sub-*/anat/*_T1w.nii.gz", "sub-*/ses-*/anat/*_T1w.nii.gz")


def split_ext(path):
    """
    Split a filename into stem and extension, keeping `.nii.gz` together.

    >>> split_ext("sub-01/anat/sub-01_T1w.nii.gz")
    ('sub-01_T1w', '.nii.gz')
    """
    name = Path(path).name
    stem = Path(name.removesuffix(".gz").removesuffix(".xz")).stem
    return stem, name[len(stem):]


def parse(path):
    """
    Read the BIDS entities of a filename into a dict.

    >>> parse("sub-01_ses-pre_run-2_T1w.nii.gz")
    {'sub': '01', 'ses': 'pre', 'run': '2', 'suffix': 'T1w', 'extension': '.nii.gz'}
    """
    stem, extension = split_ext(path)
    *entity_tokens, suffix = stem.split("_")
    entities = {}
    for token in entity_tokens:
        key, _, value = token.partition("-")
        entities[key] = value
    entities["suffix"] = suffix
    entities["extension"] = extension
    return entities


def find_t1w(bids_dir):
    """
    Every T1w image of the dataset, sorted, as `{"path", "entities", "stem"}`.

    `stem` is the filename without `_T1w.nii.gz` (e.g. `sub-01_ses-pre_run-2`):
    it keeps every entity, so derivative names stay unique across sessions,
    runs and acquisitions.
    """
    bids_dir = Path(bids_dir)
    paths = sorted(path for pattern in T1W_GLOBS for path in bids_dir.glob(pattern))
    return [
        {
            "path": str(path),
            "entities": parse(path),
            "stem": split_ext(path)[0].removesuffix("_T1w"),
        }
        for path in paths
    ]


def list_subjects(bids_dir):
    """Subject labels (without `sub-`) of every `sub-*` folder in the dataset."""
    return sorted(path.name.removeprefix("sub-")
                  for path in Path(bids_dir).glob("sub-*") if path.is_dir())


def derivative_mask_path(derivatives_dir, tool_name, t1w):
    """
    Where a tool's mask for one T1w lives, following BIDS derivatives:
    `<derivatives>/<tool>/sub-X/[ses-Y/]anat/<stem>_desc-brain_mask.nii.gz`.
    """
    entities = t1w["entities"]
    folder = Path(derivatives_dir) / tool_name / f"sub-{entities['sub']}"
    if "ses" in entities:
        folder = folder / f"ses-{entities['ses']}"
    return folder / "anat" / f"{t1w['stem']}_desc-brain_mask.nii.gz"
