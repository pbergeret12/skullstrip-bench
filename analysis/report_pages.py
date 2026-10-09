"""
The report is split into pages of a fixed number of participants, so that
each page stays light enough for a browser (every picture is embedded):

    <output>/report.html            the entry page: one line per page, with progress
    <output>/pages/page_001.html    the participants of page 1, and so on

A participant always lands on the same page (pages follow the planned order of
participants), so a page fills up as its participants finish, and only that
page and the entry page are rebuilt when one of them does. The page size is
`participants_per_page` in the plan; changing it only re-splits the existing
parts, nothing is recomputed.
"""
import html
from datetime import datetime
from pathlib import Path
from string import Template

from analysis.assemble import list_parts, rebuild_from_parts, write_atomically
from analysis.layout import report_path, state_path

INDEX_TEMPLATE = Path(__file__).with_name("report_index_template.html")
DEFAULT_PER_PAGE = 20


def subject_pages(plan):
    """The planned participants (`sub-X`), in order, split into pages."""
    per_page = plan.get("participants_per_page") or DEFAULT_PER_PAGE
    subjects = plan["subjects"]
    return [subjects[start:start + per_page] for start in range(0, len(subjects), per_page)]


def page_of(plan, subject):
    """The page number (from 1) of a participant label (without `sub-`)."""
    for number, page in enumerate(subject_pages(plan), start=1):
        if f"sub-{subject}" in page:
            return number
    return None


def page_file(output_dir, number):
    return report_path(output_dir, "pages", f"page_{number:03d}.html")


def rebuild_pages(plan, numbers, render):
    """
    Rebuild the given pages from their participants' parts, then the entry
    page. `render(parts, number, pages)` returns a page's HTML. Returns how
    many participants are processed so far.
    """
    output_dir = plan["output_dir"]
    pages = subject_pages(plan)
    for number in numbers:
        names = {f"{subject}.html" for subject in pages[number - 1]}
        rebuild_from_parts(state_path(output_dir, "report_parts"), ".html",
                           page_file(output_dir, number),
                           lambda parts, number=number: render(parts, number, pages), names)
    for stale in report_path(output_dir, "pages").glob("page_*.html"):
        if int(stale.stem.split("_")[1]) > len(pages):
            stale.unlink()   # left over from a larger number of pages
    return rebuild_index(plan, pages)


def rebuild_index(plan, pages):
    """Write the entry page, report.html: one line per page, with its progress."""
    output_dir = plan["output_dir"]
    done = {part.stem for part in list_parts(state_path(output_dir, "report_parts"), ".html")}
    rows = []
    for number, page in enumerate(pages, start=1):
        processed = sum(subject in done for subject in page)
        label = f"Page {number}"
        if page_file(output_dir, number).is_file():
            label = f'<a href="pages/{page_file(output_dir, number).name}">{label}</a>'
        rows.append(f"<tr><td>{label}</td>"
                    f"<td>{html.escape(page[0])} to {html.escape(page[-1])}</td>"
                    f'<td class="count">{processed} / {len(page)}</td></tr>')
    write_atomically(report_path(output_dir, "report.html"), Template(
        INDEX_TEMPLATE.read_text()).substitute(
            n_done=len(done), n_planned=len(plan["subjects"]),
            tools=", ".join(sorted(plan["tools"])),
            updated=datetime.now().strftime("%Y-%m-%d %H:%M"),
            per_page=len(pages[0]) if pages else 0, rows="\n".join(rows)))
    return len(done)


def navigation(number, n_pages):
    """Links from a page to the entry page and its neighbours."""
    links = ['<a href="../report.html">All pages</a>']
    if number > 1:
        links.append(f'<a href="page_{number - 1:03d}.html">Previous page</a>')
    if number < n_pages:
        links.append(f'<a href="page_{number + 1:03d}.html">Next page</a>')
    return " ".join(links)
