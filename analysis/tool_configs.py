"""
Read and validate the tool configurations in `tools/` (one YAML per tool).

A tool config looks like:

    name: synthstrip                    # must match the file name
    image: freesurfer/synthstrip:1.8    # Docker reference
    container: synthstrip_1.8           # <containers>/synthstrip_1.8.tar or .sif
    command: mri_synthstrip -i {input} -m {mask} -t {threads}
    mask_output: "{mask}"               # optional: where the tool writes its mask
    postprocess: labels_to_mask         # optional: turn the output into a mask
    requires: [atlas.nii.gz]            # optional: files in container_requirements/<name>/
    timeout_min: 30                     # optional: stop a run after 30 minutes
    cpus: 4                             # cluster resources for one run
    mem_gb: 8
    minutes: 5                          # expected duration of one run on a cluster

Files a tool needs besides its image (atlases, templates, configs) ship with
this project, in container_requirements/<name>/ (and inside the tool's own
container), mounted read-only as `{requirements}`: users bring only their
images and their dataset.
"""
from pathlib import Path
from string import Formatter

import yaml

REQUIRED_KEYS = ("name", "image", "container", "command")
OPTIONAL_KEYS = ("mask_output", "postprocess", "requires", "timeout_min",
                 "cpus", "mem_gb", "minutes")
NUMBER_KEYS = ("timeout_min", "cpus", "mem_gb", "minutes")
PLACEHOLDERS = {"input", "mask", "output_prefix", "requirements", "threads"}
POSTPROCESSES = {"labels_to_mask"}  # implemented in analysis/postprocess.py
DEFAULT_RESOURCES = {"cpus": 1, "mem_gb": 4, "minutes": 10}


def load_tools(tools_dir):
    """
    Load every `tools/*.yaml`.

    Returns `(tools, problems)`: `tools` maps a tool name to its config (with
    defaults filled in), `problems` maps the name of each invalid config to
    the reason it was rejected.
    """
    tools, problems = {}, {}
    for path in sorted(Path(tools_dir).glob("*.yaml")):
        try:
            config = yaml.safe_load(path.read_text())
            problem = config_problem(config, path.stem)
        except yaml.YAMLError as error:
            problem = f"is not valid YAML ({error})"
        if problem:
            problems[path.stem] = problem
            continue
        tools[path.stem] = {"mask_output": "{mask}", "requires": [],
                            **DEFAULT_RESOURCES, **config}
    return tools, problems


def config_problem(config, expected_name):
    """The first thing wrong with a tool config, or None if it is valid."""
    if not isinstance(config, dict):
        return "is not a mapping"
    missing = [key for key in REQUIRED_KEYS if not config.get(key)]
    if missing:
        return f"is missing {', '.join(missing)}"
    unknown = set(config) - set(REQUIRED_KEYS) - set(OPTIONAL_KEYS)
    if unknown:
        return f"has unknown keys {', '.join(sorted(unknown))}"
    if config["name"] != expected_name:
        return f"is named '{config['name']}', expected '{expected_name}' (the file name)"
    for key in ("command", "mask_output"):
        bad = placeholders(config.get(key, "")) - PLACEHOLDERS
        if bad:
            return f"uses unknown placeholders in {key}: {', '.join(sorted(bad))}"
    if config.get("postprocess", "labels_to_mask") not in POSTPROCESSES:
        return f"has unknown postprocess '{config['postprocess']}'"
    for key in NUMBER_KEYS:
        if key in config and not is_positive_number(config[key]):
            return f"has {key} '{config[key]}', expected a positive number"
    requires = config.get("requires", [])
    if not isinstance(requires, list) or not all(isinstance(name, str) for name in requires):
        return "has requires that is not a list of file names"
    return None


def is_positive_number(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and value > 0


def placeholders(template):
    """The `{names}` used in a command template."""
    return {field for _, field, _, _ in Formatter().parse(template) if field}


def missing_requirements(tool, requirements_dir):
    """The files the tool requires that are not in `<requirements_dir>/<tool>/`."""
    if not tool["requires"]:
        return []
    if requirements_dir is None:
        return list(tool["requires"])
    folder = Path(requirements_dir) / tool["name"]
    return [name for name in tool["requires"] if not (folder / name).is_file()]
