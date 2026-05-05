#!/usr/bin/env python3
"""Convert a Markdown morning digest into a styled PDF matching the user's sample.

Usage:
    python build_digest_pdf.py input.md output.pdf
"""

from __future__ import annotations

import argparse
from pathlib import Path

import markdown
from weasyprint import HTML


CSS = """
@page {
  size: A4;
  margin: 15mm 15mm;
}
body {
  font-family: "Helvetica", "Arial", sans-serif;
  color: #333;
  line-height: 1.5;
  font-size: 10pt;
}
h1 {
  font-size: 24pt;
  margin-bottom: 4pt;
  color: #000;
  display: inline-block;
}
.header-date {
  float: right;
  font-size: 10pt;
  color: #666;
  margin-top: 12pt;
}
hr {
  border: 0;
  border-top: 1px solid #000;
  margin: 10pt 0;
}
h2 {
  font-size: 9pt;
  color: #999;
  text-transform: uppercase;
  background: #f9f9f9;
  padding: 4pt 8pt;
  margin-top: 15pt;
  margin-bottom: 10pt;
  letter-spacing: 1pt;
}
h3 {
  font-size: 11pt;
  margin-top: 12pt;
  margin-bottom: 2pt;
  color: #000;
}
p {
  margin-top: 0;
  margin-bottom: 8pt;
}
.source-link {
  font-size: 8pt;
  color: #999;
  font-style: italic;
  word-break: break-all;
}
table {
  width: 100%;
  border-collapse: collapse;
  margin-bottom: 10pt;
}
td {
  padding: 4pt 0;
  vertical-align: top;
}
.time-col {
  width: 80pt;
  color: #666;
}
.event-col {
  font-weight: bold;
}
.footer {
  text-align: center;
  font-size: 8pt;
  color: #999;
  margin-top: 20pt;
  font-style: italic;
}
a {
  color: #999;
  text-decoration: none;
}
"""


def convert(markdown_path: Path, pdf_path: Path) -> None:
    if not markdown_path.exists():
        raise FileNotFoundError(f"Markdown input not found: {markdown_path}")

    markdown_text = markdown_path.read_text(encoding="utf-8")
    
    # Extract date from H1 if possible
    lines = markdown_text.split('\n')
    title = "Morning Digest"
    date_str = ""
    if lines and lines[0].startswith('# '):
        parts = lines[0][2:].split(' — ')
        title = parts[0]
        if len(parts) > 1:
            date_str = parts[1]
        markdown_text = '\n'.join(lines[1:])

    html_body = markdown.markdown(
        markdown_text,
        extensions=["tables", "fenced_code", "sane_lists"],
        output_format="html5",
    )
    
    # Post-process HTML to add classes for styling
    html_body = html_body.replace('<table>', '<table class="schedule-table">')
    
    html_doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<style>{CSS}</style>
</head>
<body>
    <div class="header">
        <span class="header-date">{date_str}</span>
        <h1>{title}</h1>
    </div>
    <hr>
    {html_body}
    <div class="footer">
        News updated: {date_str} | Calendar & email: live snapshot
    </div>
</body>
</html>
"""
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    HTML(string=html_doc, base_url=str(markdown_path.parent)).write_pdf(str(pdf_path))


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a styled PDF from a Markdown morning digest.")
    parser.add_argument("input_markdown", type=Path, help="Path to the Markdown digest file")
    parser.add_argument("output_pdf", type=Path, help="Path where the PDF should be written")
    args = parser.parse_args()
    convert(args.input_markdown, args.output_pdf)
    print(f"Wrote PDF: {args.output_pdf}")


if __name__ == "__main__":
    main()
