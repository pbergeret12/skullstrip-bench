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
