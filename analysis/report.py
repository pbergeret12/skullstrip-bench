"""
`run-report`: a single self-contained HTML file to judge every mask by eye.

One row per T1w, one column per tool. Each cell shows the mask's outline on the
T1w (click it for a large, zoomable version), its metrics, and OK / Fail /
Doubtful buttons with a comment field; the notes are exported as CSV by the
page itself (no server). Images are embedded in base64, so the file can be
shared alone.
"""
import base64
import html
from datetime import date
from pathlib import Path
from string import Template

import pandas as pd

from analysis.metrics import load_records
from analysis.report_figures import draw_mask_outline

TEMPLATE_FILE = Path(__file__).with_name("report_template.html")
STATUS_LABELS = {"failed": "Failed", "oom": "Failed: out of memory",
                 "timeout": "Failed: timed out"}
MAX_ERROR_CHARACTERS = 600


def build_report(runs_dir, metrics_csv, figures_dir, output_html, plausible_volume_ml):
    """Draw the missing figures, then write the report."""
    records = {(record["stem"], record["tool"]): record for record in load_records(runs_dir)}
    draw_figures(runs_dir, figures_dir)

    metrics = pd.read_csv(metrics_csv).set_index(["stem", "tool"])
    tools = sorted({tool for _, tool in records})
    stems = sorted({stem for stem, _ in records})
    rows = [row_html(stem, tools, records, metrics, figures_dir, plausible_volume_ml)
            for stem in stems]

    page = Template(TEMPLATE_FILE.read_text()).substitute(
        date=date.today().isoformat(),
        n_t1w=len(stems),
        tools=", ".join(tools),
        volume_min=plausible_volume_ml[0],
        volume_max=plausible_volume_ml[1],
        header_cells="".join(f"<th>{html.escape(tool)}</th>" for tool in tools),
        rows="\n".join(rows),
    )
    Path(output_html).write_text(page)


def figure_paths(figures_dir, stem, tool):
    """The run's thumbnail and full-size picture."""
    folder = Path(figures_dir) / tool
    return folder / f"{stem}.jpg", folder / f"{stem}_full.jpg"


def draw_figures(runs_dir, figures_dir, subjects=None):
    """
    Draw the pictures of every successful run that does not have them yet,
    optionally only for some subjects (a cluster array task draws its own).
    """
    for record in load_records(runs_dir):
        stem, tool = record["stem"], record["tool"]
        if subjects and record["subject"] not in subjects:
            continue
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
        thumbnail, full = (embedded_jpeg(path) for path in figures)
        body = (f'<img src="{thumbnail}" data-full="{full}" alt="{html.escape(stem)} {tool}">'
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
    """OK / Fail / Doubtful buttons and a comment box (wired by the page's script)."""
    buttons = "".join(f'<button type="button" data-rating="{rating}">{label}</button>'
                      for rating, label in (("ok", "OK"), ("fail", "Fail"),
                                            ("doubtful", "Doubtful")))
    return (f'<div class="rating">{buttons}</div>'
            '<textarea placeholder="Comment" rows="2"></textarea>')


def embedded_jpeg(path):
    """A JPEG file as a data URI, so the report needs no other file."""
    return "data:image/jpeg;base64," + base64.b64encode(Path(path).read_bytes()).decode()


def fmt(value, spec, missing=""):
    """Format a number, or `missing` when it is NaN (a failed run, a lone tool)."""
    return missing if pd.isna(value) else format(value, spec)
