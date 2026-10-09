# Output data

This is the default output folder (`--output`); any other output folder gets
the same layout. It holds the report and nothing else visible.

`report.html` is the self-contained visual report (images embedded), to open
in a browser at any time and rate each mask Good, Bad or Uncertain. It grows
as participants finish, so reload it to see the latest.

`figures/` holds its pictures: figures/TOOL/STEM.jpg as the thumbnail and
STEM_full.jpg for the zoom viewer, the T1w with the mask's outline in red.

`metrics.csv` has one row per run: subject, stem, tool, status, volume_ml,
dice_consensus (against the majority vote of the tools that succeeded on that
T1w, empty with fewer than two), n_tools_consensus, duration_s, error.

The logs are not here: they go to `logs/` in the working directory the
command is run from (or `--workdir`), together with the sbatch script and
jobs.txt in cluster mode.

Everything else is internal to the tool and lives in the hidden folder
.skullstrip-bench/: the plan written by `run-check`, one record per run (its
status, duration and error, and the marker that lets a repeated run skip it),
the validated masks (kept to recompute the Dice when a run is retried or a
tool added), the per-participant parts from which metrics.csv and report.html
are rebuilt, and the provenance records MANIFEST.json (what each input path
resolved to) and PROVENANCE.json (what produced the outputs). The raw files
each tool writes are deleted at the end of its run.

Everything here is ignored by git except the two provenance records: the
report and the masks show participants' brains, and the metrics are
per-participant data.
