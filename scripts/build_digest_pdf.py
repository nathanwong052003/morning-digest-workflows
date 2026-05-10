#!/usr/bin/env python3
"""Convert a styled HTML digest file to a PDF using WeasyPrint.

This script handles only the PDF export — edit render_digest.py for visual changes.

Usage:
    python build_digest_pdf.py input.html output.pdf

Prerequisites:
    pip install weasyprint --break-system-packages

Note: Playwright/Chromium is NOT used by default. WeasyPrint is the primary engine
because it works without a network download at runtime. If you need Playwright instead,
install it separately: pip install playwright && playwright install chromium
"""

from __future__ import annotations

import argparse
from pathlib import Path


def convert(html_path: Path, pdf_path: Path) -> None:
    if not html_path.exists():
        raise FileNotFoundError(f"HTML input not found: {html_path}")

    pdf_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        from weasyprint import HTML, CSS
    except ImportError:
        raise ImportError(
            "WeasyPrint is not installed. Run:\n"
            "  pip install weasyprint --break-system-packages"
        )

    # Inline font CSS — avoids any external Google Fonts network call at render time.
    # WeasyPrint falls back gracefully to system sans-serif if local fonts are absent.
    font_css = CSS(string="""
        @font-face {
            font-family: 'Poppins';
            font-weight: 600 700;
            src: local('Poppins');
        }
        @font-face {
            font-family: 'Lato';
            font-weight: 400 700;
            src: local('Lato');
        }
    """)

    html = HTML(filename=str(html_path))
    html.write_pdf(str(pdf_path), stylesheets=[font_css])
    print(f"Wrote PDF: {pdf_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert HTML digest to PDF via WeasyPrint.")
    parser.add_argument("input_html", type=Path)
    parser.add_argument("output_pdf", type=Path)
    args = parser.parse_args()
    convert(args.input_html, args.output_pdf)


if __name__ == "__main__":
    main()
