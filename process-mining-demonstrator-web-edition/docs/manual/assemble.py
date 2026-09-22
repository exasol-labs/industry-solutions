"""Assemble the chapter fragments into a paginated A4 PDF manual.

Two passes: render once to discover which page each chapter starts on, then rewrite the
table of contents with real page numbers and render again.
"""
import base64
import datetime
import pathlib
import re
import sys

from playwright.sync_api import sync_playwright
from pypdf import PdfReader

# All paths are relative to THIS file, so the build runs from the repo unchanged.
MAN = pathlib.Path(__file__).resolve().parent            # docs/manual/
REPO = MAN.parent.parent                                 # repo root
CHAPTERS_DIR = MAN / "chapters"
SHOTS = MAN / "screenshots"
LOGO = REPO / "frontend" / "web" / "public" / "logo.svg"

PARTS = [
    (1, "Part I", "Getting Started", range(1, 5)),
    (2, "Part II", "Using the Application", range(5, 12)),
    (3, "Part III", "Administration", range(12, 16)),
    (4, "Part IV", "The Integration Console", range(16, 21)),
    (5, "Part V", "Reference", range(21, 25)),
    (6, "Part VI", "Actions", range(25, 26)),
    (7, "Part VII", "The API Server - Event Receiver", range(26, 27)),
    (8, "Part VIII", "The MCP Server", range(27, 99)),
]

DATE = datetime.date.today().strftime("%d %B %Y")


def data_uri(path: pathlib.Path) -> str:
    mime = "image/svg+xml" if path.suffix == ".svg" else "image/png"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


def load_chapters():
    out = []
    for f in sorted(CHAPTERS_DIR.glob("*.html")):
        html = f.read_text()
        m = re.search(r'<section[^>]*data-num="(\d+)"[^>]*data-title="([^"]+)"', html)
        if not m:
            m2 = re.search(r'<section[^>]*data-title="([^"]+)"[^>]*data-num="(\d+)"', html)
            if m2:
                num, title = int(m2.group(2)), m2.group(1)
            else:
                num, title = int(f.name.split("-")[0]), f.stem.split("-", 1)[1].replace("-", " ").title()
        else:
            num, title = int(m.group(1)), m.group(2)
        out.append({"num": num, "title": title, "html": html, "file": f})
    out.sort(key=lambda c: c["num"])
    return out


FIG_RE = re.compile(r'<figure[^>]*data-fig="([^"]+)"[^>]*>(.*?)</figure>', re.S)


def resolve_figures(html: str, chapter_num: int):
    """Replace <figure data-fig="KEY"> with a real image, or drop it if missing."""
    counter = {"n": 0}
    missing = []

    def repl(m):
        key, inner = m.group(1), m.group(2)
        png = SHOTS / f"{key}.png"
        if not png.exists():
            missing.append(key)
            return ""
        counter["n"] += 1
        label = f"Figure {chapter_num}.{counter['n']}"
        cap = re.search(r"<figcaption[^>]*>(.*?)</figcaption>", inner, re.S)
        caption = cap.group(1).strip() if cap else ""
        return (
            f'<figure><img src="{data_uri(png)}" alt="{label}">'
            f'<figcaption><span class="figlabel">{label}</span> — {caption}</figcaption></figure>'
        )

    return FIG_RE.sub(repl, html), missing


def build_html(chapters, page_map=None):
    parts_html = []
    toc_rows = []
    for _pn, plabel, ptitle, rng in PARTS:
        members = [c for c in chapters if c["num"] in rng]
        if not members:
            continue
        toc_rows.append(f'<li class="toc-part">{plabel} · {ptitle}</li>')
        for c in members:
            pg = page_map.get(c["num"], "") if page_map else ""
            toc_rows.append(
                f'<li><span class="tnum">{c["num"]}</span>'
                f'<span class="ttitle">{c["title"]}</span>'
                f'<span class="tdots"></span><span class="tpage">{pg}</span></li>'
            )
        parts_html.append(
            f'<section class="part"><div class="pnum">{plabel}</div>'
            f"<h1>{ptitle}</h1>"
            f'<div class="rule"></div></section>'
        )

    body = []
    for _pn, plabel, ptitle, rng in PARTS:
        members = [c for c in chapters if c["num"] in rng]
        if not members:
            continue
        body.append(
            f'<section class="part"><div class="pnum">{plabel}</div>'
            f"<h1>{ptitle}</h1><div class=\"rule\"></div></section>"
        )
        for c in members:
            html, missing = resolve_figures(c["html"], c["num"])
            if missing:
                print(f"  chapter {c['num']}: dropped missing figures {sorted(set(missing))}")
            body.append(html)

    css = (MAN / "manual.css").read_text()
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Process Mining Demonstrator — User Manual</title>
<style>{css}</style></head>
<body>

<section class="cover">
  <img class="logo" src="{data_uri(LOGO)}" alt="">
  <h1>Process Mining<br>Demonstrator</h1>
  <div class="edition">Web Edition — User Manual</div>
  <div class="rule"></div>
  <p class="sub">The complete guide to the application, the administration
  interface and the data-source integration console.</p>
  <div class="meta">
    <strong>Offline edition</strong><br>
    Generated {DATE}<br>
    For demonstration and educational use
  </div>
</section>

<section class="frontmatter">
  <h2>About this manual</h2>
  <p>This manual documents the <strong>Process Mining Demonstrator — Web Edition</strong>
  in full: the analysis application, the administration interface and the integration
  console for loading data. It is written to be read offline and used as a reference,
  so every screen, control, option and error message is described where the behaviour
  is defined by the product.</p>

  <div class="warn"><strong>Scope</strong> This application is intended for
  demonstration and educational purposes. It is not a production-ready process mining
  solution, and it should not be used for business-critical decisions without
  independent verification.</div>

  <h2>How this manual is organised</h2>
  <p>The manual is divided into seven parts. <em>Part I</em> introduces process mining and
  gets you to your first process map. <em>Part II</em> covers the analysis application in
  depth. <em>Part III</em> is for administrators. <em>Part IV</em> covers loading your own
  data through the integration console. <em>Part V</em> is reference material: the data
  model, the extractor API, troubleshooting and a glossary. <em>Part VI</em> covers Actions,
  the business-readable queries you attach to process-map nodes. <em>Part VII</em> covers the
  API Server - Event Receiver, the push API for logging events from an external program.</p>

  <h2>Conventions</h2>
  <dl>
    <dt>On-screen labels</dt>
    <dd>Names of buttons, fields and menu items appear exactly as they do in the
    interface, for example <strong>Run extraction</strong> or <strong>Delta upload</strong>.</dd>
    <dt>Procedures</dt>
    <dd>Numbered lists are step-by-step instructions to be followed in order.</dd>
    <dt>Commands and code</dt>
    <dd>Shell commands, configuration values and API bodies appear in a
    <code>monospaced</code> typeface.</dd>
  </dl>
  <div class="note"><strong>Note</strong> Additional context or a detail that is easy to miss.</div>
  <div class="tip"><strong>Tip</strong> A suggestion that makes a task easier or faster.</div>
  <div class="warn"><strong>Warning</strong> Something that can lose data, expose
  information, or is hard to undo. Read these before acting.</div>
  <div class="role">Requires: <b>Administrator</b> — a capability callout naming the role
  needed for the task described.</div>

  <h2>Screenshots</h2>
  <p>Screenshots were taken from a live instance loaded with the bundled demonstration
  datasets (“Online Bookstore” and “Online Credit Application”). Your own figures will
  differ in data but not in layout.</p>
</section>

<section class="toc">
  <h2>Contents</h2>
  <ol>{''.join(toc_rows)}</ol>
</section>

{''.join(body)}
</body></html>
"""


def render(html_path: pathlib.Path, pdf_path: pathlib.Path):
    with sync_playwright() as pw:
        b = pw.chromium.launch(channel="chrome")
        page = b.new_page()
        page.goto(f"file://{html_path}", wait_until="networkidle")
        page.wait_for_timeout(2500)
        page.pdf(
            path=str(pdf_path),
            format="A4",
            print_background=True,
            display_header_footer=True,
            header_template="<div></div>",
            footer_template=(
                '<div style="width:100%;font-size:8pt;color:#8a90a0;'
                'font-family:Helvetica,Arial,sans-serif;padding:0 18mm;'
                'display:flex;justify-content:space-between;">'
                "<span>Process Mining Demonstrator — Web Edition · User Manual</span>"
                '<span class="pageNumber"></span></div>'
            ),
            margin={"top": "18mm", "bottom": "16mm", "left": "18mm", "right": "18mm"},
        )
        b.close()


def _norm(s: str) -> str:
    """Normalise smart punctuation and whitespace so HTML-derived strings match the text
    the PDF engine renders (curly quotes, em dashes, entities)."""
    for a, b in [("’", "'"), ("‘", "'"), ("“", '"'), ("”", '"'),
                 ("—", " "), ("–", "-"), ("‐", "-"),
                 ("ﬁ", "fi"), ("ﬂ", "fl"), ("ﬀ", "ff"), ("ﬃ", "ffi"), ("ﬄ", "ffl"),
                 ("&rsquo;", "'"), ("&lsquo;", "'"), ("&mdash;", " "),
                 ("&ldquo;", '"'), ("&rdquo;", '"'), ("&amp;", "&")]:
        s = s.replace(a, b)
    return " ".join(s.split())


def _fingerprint(html: str) -> str:
    """A distinctive run of words from the chapter's intro paragraph. It appears only in
    the chapter body, never in the table of contents, so it identifies the opening page."""
    m = re.search(r'<p class="chintro">(.*?)</p>', html, re.S)
    if not m:
        return ""
    text = _norm(re.sub(r"<[^>]+>", "", m.group(1)))
    return " ".join(text.split(" ")[:7])


def page_numbers(pdf_path: pathlib.Path, chapters):
    """The first page carrying both a chapter's heading and its intro fingerprint. The
    fingerprint is what distinguishes the real opening page from the contents listing."""
    reader = PdfReader(str(pdf_path))
    fps = {c["num"]: _fingerprint(c["html"]) for c in chapters}
    found = {}
    for idx, pg in enumerate(reader.pages, start=1):
        try:
            text = _norm(pg.extract_text() or "")
        except Exception:
            continue
        for c in chapters:
            if c["num"] in found:
                continue
            head = _norm(f"{c['num']} {c['title']}")
            fp = fps.get(c["num"], "")
            if fp and fp in text and head in text:
                found[c["num"]] = idx
            elif not fp and head in text[:120]:
                found[c["num"]] = idx
    return found


def main():
    chapters = load_chapters()
    print(f"chapters: {len(chapters)} -> {[c['num'] for c in chapters]}")
    if not chapters:
        sys.exit("no chapters found")

    html_path = MAN / "manual.html"
    pdf_path = MAN / "Process-Mining-Demonstrator-Manual.pdf"

    print("pass 1 (discover page numbers)…")
    html_path.write_text(build_html(chapters))
    render(html_path, pdf_path)
    pages = page_numbers(pdf_path, chapters)
    print("  located:", {k: pages[k] for k in sorted(pages)})

    print("pass 2 (final with TOC page numbers)…")
    html_path.write_text(build_html(chapters, pages))
    render(html_path, pdf_path)

    reader = PdfReader(str(pdf_path))
    size_mb = pdf_path.stat().st_size / 1e6
    print(f"\nDONE  {pdf_path}\n  {len(reader.pages)} pages, {size_mb:.1f} MB")


main()
