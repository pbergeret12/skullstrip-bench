"""
Read and validate the tool configurations in `tools/` (one YAML per tool).

A tool config looks like:

    name: synthstrip                    # must match the file name
    image: freesurfer/synthstrip:1.8    # Docker reference
    container: synthstrip_1.8           # <containers>/synthstrip_1.8.tar or .sif
    command: mri_synthstrip -i {input} -m {mask}
    mask_output: "{mask}"               # optional: where the tool writes its mask
    postprocess: labels_to_mask         # optional: turn the output into a mask
    timeout_min: 30                     # optional: stop a run after 30 minutes

Annex files (templates, ...) go in `tools/<name>/`, mounted as `{tool_dir}`.
"""
from pathlib import Path
from string import Formatter

import yaml

REQUIRED_KEYS = ("name", "image", "container", "command")
OPTIONAL_KEYS = ("mask_output", "postprocess", "timeout_min")
PLACEHOLDERS = {"input", "mask", "output_prefix", "tool_dir"}
POSTPROCESSES = {"labels_to_mask"}  # implemented in analysis/postprocess.py


def load_tools(tools_dir):
    """
    Load every `tools/*.yaml`.

    Returns `(tools, problems)`: `tools` maps a tool name to its config (with
    `mask_output` defaulted to `{mask}`), `problems` maps the name of each
    invalid config to the reason it was rejected.
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
        config.setdefault("mask_output", "{mask}")
        tools[path.stem] = config
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
    timeout = config.get("timeout_min", 1)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
        return f"has timeout_min '{timeout}', expected a positive number of minutes"
    if config.get("postprocess", "labels_to_mask") not in POSTPROCESSES:
        return f"has unknown postprocess '{config['postprocess']}'"
    return None


def placeholders(template):
    """The `{names}` used in a command template."""
    return {field for _, field, _, _ in Formatter().parse(template) if field}
