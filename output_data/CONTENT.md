# Output data

This is the default output folder (`--output`); any other output folder gets
the same layout. Once the pipeline has run, it shows two folders.

`report/` holds report.html, the self-contained visual report (images
embedded), to open in a browser at any time and rate each mask Good, Bad or
Uncertain; it grows as participants finish, so reload it to see the latest.
Next to it, figures/ holds its pictures (figures/TOOL/STEM.jpg as the
thumbnail and STEM_full.jpg for the zoom viewer, the T1w with the mask's
outline in red), and metrics.csv has one row per run: subject, stem, tool,
status, volume_ml, dice_consensus (against the majority vote of the tools
that succeeded on that T1w, empty with fewer than two), n_tools_consensus,
duration_s, error.

`logs/` holds, for each run, logs/TOOL/STEM.log (what the container printed,
after a first line with the exact command and before a last line with the
run's status) and logs/TOOL/STEM.err (the container's errors, ending with why
the run failed if it did). With `--scheduler slurm`, logs/slurm/ holds the
jobs' own .log and .err.

`slurm/`, only with `--scheduler slurm` (running on an HPC): the generated
sbatch scripts for the user to edit and submit. jobs.txt has one participant
per line; skullstrip_array.sh is the job array (task N processes line N,
`--array=1-N` covers everyone, `--account=def-CHANGEME` is to be replaced
with the user's allocation); skullstrip_report.sh rebuilds metrics and
report once the array has ended; submit.sh submits both.

Everything else is internal to the tool and lives in the hidden folder
.skullstrip-bench/: the plan written by `run-check`, one record per run (its
status, duration and error, and the marker that lets a repeated run skip it),
the validated masks (kept to recompute the Dice when a run is retried or a
tool added), the per-participant parts from which metrics.csv and report.html
are rebuilt, and the provenance records
MANIFEST.json (what each input path resolved to) and PROVENANCE.json (what
produced the outputs). The raw files each tool writes are deleted at the end
of its run.

Everything here is ignored by git except the two provenance records: the
report and the masks show participants' brains, and the metrics and logs are
per-participant data.
