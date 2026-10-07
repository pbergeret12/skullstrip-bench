from analysis.assemble import rebuild_from_parts, write_atomically


def test_part_written_during_a_rebuild_is_not_lost(tmp_path):
    parts_dir, output = tmp_path / "parts", tmp_path / "all.txt"
    write_atomically(parts_dir / "sub-01.txt", "one\n")

    def build(parts):
        # Another job finishes while this one is assembling.
        if not (parts_dir / "sub-02.txt").exists():
            write_atomically(parts_dir / "sub-02.txt", "two\n")
        return "".join(part.read_text() for part in parts)

    parts = rebuild_from_parts(parts_dir, ".txt", output, build)
    assert [part.name for part in parts] == ["sub-01.txt", "sub-02.txt"]
    assert output.read_text() == "one\ntwo\n"
    assert not list(tmp_path.rglob(".*.tmp"))   # no temporary file left behind
