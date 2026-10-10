"""
`run-report`: one HTML page, `report.html`, to judge every mask by eye.

One row per T1w, one column per tool. Each cell shows the mask's outline on the
T1w (click it for a large, zoomable version), its metrics, and Good / Bad /
Uncertain buttons with a comment field; the notes are exported as CSV by the
page itself (no server).

The pictures are not embedded: the page points to the files in `figures/`
next to it and the browser loads them lazily, only those on screen (and the
full-size one on click). The page itself stays small, so hundreds of
participants fit on it; to move or share the report, keep report.html and
figures/ together.

The report is incremental: as soon as a participant is done, its rows are
written to their own part (internal state) and `report.html` is rebuilt from
every part present. It can be opened at any time; reloading it shows the
participants finished since.
"""
import html
from datetime import datetime
from pathlib import Path
from string import Template

import pandas as pd

from analysis.assemble import rebuild_from_parts, write_atomically
from analysis.layout import report_path, state_path
from analysis.metrics import load_records
from analysis.report_figures import draw_mask_outline

TEMPLATE_FILE = Path(__file__).with_name("report_template.html")
STATUS_LABELS = {"failed": "Failed", "oom": "Failed: out of memory",
                 "timeout": "Failed: timed out"}
RATINGS = (("good", "Good"), ("bad", "Bad"), ("uncertain", "Uncertain"))
MAX_ERROR_CHARACTERS = 600


def update_report(plan, subjects, plausible_volume_ml):
    """
    Rewrite the report part of each subject (drawing its missing pictures),
    then rebuild `report.html`. Expects the subjects' metrics parts to exist.
    Returns how many participants are processed.
    """
    output_dir = Path(plan["output_dir"])
    tools = sorted(plan["tools"])
    for subject in subjects:
        write_subject_part(subject, tools, output_dir, plausible_volume_ml)
    parts = rebuild_from_parts(
        state_path(output_dir, "report_parts"), ".html", report_path(output_dir, "report.html"),
        lambda parts: report_page(parts, tools, len(plan["subjects"]), plausible_volume_ml))
    return len(parts)


def write_subject_part(subject, tools, output_dir, plausible_volume_ml):
    """The rows of one subject (one per T1w), saved as its report part."""
    records = {(record["stem"], record["tool"]): record
               for record in load_records(state_path(output_dir, "runs"), subject, tools)}
    part = state_path(output_dir, "report_parts", f"sub-{subject}.html")
    if not records:
        part.unlink(missing_ok=True)   # e.g. its runs were cleaned
        return
    figures_dir = report_path(output_dir, "figures")
    draw_figures(records.values(), figures_dir)
    metrics = pd.read_csv(state_path(output_dir, "metrics_parts", f"sub-{subject}.csv"))
    metrics = metrics.set_index(["stem", "tool"])
    rows = [row_html(stem, tools, records, metrics, figures_dir, plausible_volume_ml)
            for stem in sorted({stem for stem, _ in records})]
    write_atomically(part, "\n".join(rows))


def report_page(parts, tools, n_planned, plausible_volume_ml):
    """The whole page: header, progress, then every part's rows."""
    return Template(TEMPLATE_FILE.read_text()).substitute(
        updated=datetime.now().strftime("%Y-%m-%d %H:%M"),
        n_done=len(parts),
        n_planned=n_planned,
        tools=", ".join(tools),
        volume_min=plausible_volume_ml[0],
        volume_max=plausible_volume_ml[1],
        header_cells="".join(f"<th>{html.escape(tool)}</th>" for tool in tools),
        rows="\n".join(part.read_text() for part in parts),
    )


def figure_paths(figures_dir, stem, tool):
    """The run's thumbnail and full-size picture."""
    folder = Path(figures_dir) / tool
    return folder / f"{stem}.jpg", folder / f"{stem}_full.jpg"


def draw_figures(records, figures_dir):
    """Draw the pictures of every successful run that does not have them yet."""
    for record in records:
        stem, tool = record["stem"], record["tool"]
        thumbnail_file, full_file = figure_paths(figures_dir, stem, tool)
        if record["status"] == "ok" and not full_file.is_file():
            print(f"🖼️  {tool} × {stem}")
            draw_mask_outline(record["t1w"], record["mask"], thumbnail_file, full_file)


def row_html(stem, tools, records, metrics, figures_dir, plausible_volume_ml):
    """One table row: the T1w's name, then one cell per tool."""
    cells = [f'<th class="stem">{html.escape(stem)}</th>']
    for tool in tools:
        if (stem, tool) not in records:
            cells.append('<td class="cell missing">not run</td>')
            continue
        row = metrics.loc[(stem, tool)]
        cells.append(cell_html(stem, tool, row, figure_paths(figures_dir, stem, tool),
                               plausible_volume_ml))
    return "<tr>" + "".join(cells) + "</tr>"


def cell_html(stem, tool, row, figures, plausible_volume_ml):
    """One cell: picture and metrics (or the failure), then the rating controls."""
    if row["status"] == "ok":
        thumbnail, full = (figure_url(path) for path in figures)
        body = (f'<img src="{thumbnail}" data-full="{full}" loading="lazy" '
                f'alt="{html.escape(stem)} {tool}">'
                + metrics_html(row, plausible_volume_ml))
    else:
        error = str(row["error"])[:MAX_ERROR_CHARACTERS]
        body = (f'<div class="failed">{STATUS_LABELS.get(row["status"], row["status"])}</div>'
                f'<pre class="error">{html.escape(error)}</pre>')
    return (f'<td class="cell" data-stem="{html.escape(stem)}" data-tool="{html.escape(tool)}" '
            f'data-subject="{html.escape(str(row["subject"]))}" data-status="{row["status"]}" '
            f'data-volume="{fmt(row["volume_ml"], ".0f")}" '
            f'data-dice="{fmt(row["dice_consensus"], ".3f")}">'
            f'{body}{rating_html()}</td>')


def metrics_html(row, plausible_volume_ml):
    """Volume (highlighted when implausible), Dice against consensus, duration."""
    volume = row["volume_ml"]
    implausible = not plausible_volume_ml[0] <= volume <= plausible_volume_ml[1]
    volume_class = ' class="implausible"' if implausible else ""
    return ('<div class="metrics">'
            f'<span{volume_class}>{volume:.0f} mL</span>'
            f'<span>Dice {fmt(row["dice_consensus"], ".3f", "n/a")}</span>'
            f'<span>{row["duration_s"]:.0f} s</span></div>')


def rating_html():
    """Good / Bad / Uncertain buttons and a comment box (wired by the page's script)."""
    buttons = "".join(f'<button type="button" data-rating="{rating}">{label}</button>'
                      for rating, label in RATINGS)
    return (f'<div class="rating">{buttons}</div>'
            '<textarea placeholder="Comment" rows="2"></textarea>')


def figure_url(path):
    """
    A picture's address as seen from report.html (figures/<tool>/<file>),
    stamped with its modification time so that a picture redrawn after a rerun
    is not shown from the browser's cache.
    """
    path = Path(path)
    stamp = path.stat().st_mtime_ns if path.exists() else 0
    return html.escape(f"figures/{path.parent.name}/{path.name}?v={stamp}")


def fmt(value, spec, missing=""):
    """Format a number, or `missing` when it is NaN (a failed run, a lone tool)."""
    return missing if pd.isna(value) else format(value, spec)
