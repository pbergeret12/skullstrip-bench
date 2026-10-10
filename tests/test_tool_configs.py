from analysis.tool_configs import load_tools

VALID = """name: good
image: example/good:1.0
container: good_1.0
command: tool -i {input} -o {output_prefix}
mask_output: "{output_prefix}_mask.nii.gz"
"""


def write_configs(tools_dir, **configs):
    for name, text in configs.items():
        (tools_dir / f"{name}.yaml").write_text(text)


def test_valid_config_is_loaded_and_mask_output_defaults(tmp_path):
    write_configs(tmp_path, good=VALID,
                  simple="name: simple\nimage: a\ncontainer: b\ncommand: x {input} {mask}\n")
    tools, problems = load_tools(tmp_path)
    assert problems == {}
    assert tools["simple"]["mask_output"] == "{mask}"
    assert tools["good"]["mask_output"] == "{output_prefix}_mask.nii.gz"


def test_invalid_configs_are_reported(tmp_path):
    write_configs(
        tmp_path,
        missing="name: missing\nimage: a\n",
        renamed=VALID,
        placeholder=VALID.replace("good", "placeholder").replace("{input}", "{t1w}"),
        postprocess=VALID.replace("good", "postprocess") + "postprocess: magic\n",
        broken="name: [unclosed\n",
    )
    tools, problems = load_tools(tmp_path)
    assert tools == {}
    assert "missing container, command" in problems["missing"]
    assert "expected 'renamed'" in problems["renamed"]
    assert "t1w" in problems["placeholder"]
    assert "magic" in problems["postprocess"]
    assert "YAML" in problems["broken"]


def test_timeout_must_be_a_positive_number(tmp_path):
    write_configs(tmp_path,
                  slow=VALID.replace("good", "slow") + "timeout_min: 90\n",
                  zero=VALID.replace("good", "zero") + "timeout_min: 0\n",
                  word=VALID.replace("good", "word") + "timeout_min: long\n")
    tools, problems = load_tools(tmp_path)
    assert tools["slow"]["timeout_min"] == 90
    assert "timeout_min" in problems["zero"] and "timeout_min" in problems["word"]


def test_requires_and_resources(tmp_path):
    from analysis.tool_configs import missing_requirements

    atlas_command = "{output_prefix} -a {requirements}/a.nii.gz\n"
    write_configs(tmp_path,
                  atlas=VALID.replace("good", "atlas").replace("{output_prefix}\n", atlas_command)
                  + "requires: [a.nii.gz]\ncpus: 8\nmem_gb: 16\n",
                  listless=VALID.replace("good", "listless") + "requires: a.nii.gz\n",
                  oldstyle=VALID.replace("good", "oldstyle").replace("{input}", "{tool_dir}"))
    tools, problems = load_tools(tmp_path)
    atlas = tools["atlas"]
    assert (atlas["cpus"], atlas["mem_gb"], atlas["minutes"]) == (8, 16, 10)
    assert "requires" in problems["listless"]
    assert "tool_dir" in problems["oldstyle"]

    assert missing_requirements(atlas, None) == ["a.nii.gz"]
    (tmp_path / "req" / "atlas").mkdir(parents=True)
    assert missing_requirements(atlas, tmp_path / "req") == ["a.nii.gz"]
    (tmp_path / "req" / "atlas" / "a.nii.gz").write_text("")
    assert missing_requirements(atlas, tmp_path / "req") == []


def test_every_required_file_ships_with_the_project():
    """Users bring only images and a dataset: what a tool needs must be bundled."""
    from pathlib import Path

    from analysis.tool_configs import missing_requirements

    project = Path(__file__).resolve().parents[1]
    tools, problems = load_tools(project / "tools")
    assert problems == {}
    for tool in tools.values():
        assert missing_requirements(tool, project / "container_requirements") == []
