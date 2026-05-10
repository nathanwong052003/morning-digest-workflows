#!/usr/bin/env python3
"""Convert a styled HTML digest file to a PDF using WeasyPrint.

This script handles only the PDF export.

Usage:
    python build_digest_pdf.py input.html output.pdf
"""

from __future__ import annotations

import argparse
import os
import subprocess
import urllib.request
import zipfile
from pathlib import Path

_WINDOWS_DLL_DIR_HANDLES: list[object] = []
DEFAULT_WEASYPRINT_WINDOWS_ZIP_URL = (
    "https://github.com/Kozea/WeasyPrint/releases/download/v68.1/weasyprint-windows.zip"
)
FONT_CSS_STRING = """
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
"""


def _candidate_windows_dll_dirs() -> list[Path]:
    configured: list[Path] = []
    raw_env = os.getenv("WEASYPRINT_DLL_DIRECTORIES", "")
    if raw_env.strip():
        for entry in raw_env.split(os.pathsep):
            path = Path(entry.strip())
            if entry.strip():
                configured.append(path)

    # Common install paths for GTK runtime on Windows.
    defaults = [
        Path(r"C:\msys64\ucrt64\bin"),
        Path(r"C:\msys64\mingw64\bin"),
        Path(r"C:\Program Files\GTK3-Runtime Win64\bin"),
        Path(r"C:\Program Files\GTK3-Runtime\bin"),
        Path(r"C:\gtk\bin"),
    ]

    seen: set[str] = set()
    ordered: list[Path] = []
    for path in [*configured, *defaults]:
        key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(path)
    return ordered


def _configure_windows_dll_dirs() -> list[str]:
    if os.name != "nt":
        return []
    add_dll_directory = getattr(os, "add_dll_directory", None)
    if add_dll_directory is None:
        return []
    added: list[str] = []
    for path in _candidate_windows_dll_dirs():
        if not path.exists():
            continue
        try:
            handle = add_dll_directory(str(path))
        except OSError:
            continue
        _WINDOWS_DLL_DIR_HANDLES.append(handle)
        added.append(str(path))
    return added


def _has_windows_gobject_dll(extra_dirs: list[str]) -> bool:
    probe_dirs = [Path(path) for path in extra_dirs if path]
    path_env = os.getenv("PATH", "")
    if path_env:
        probe_dirs.extend(Path(part) for part in path_env.split(os.pathsep) if part.strip())
    probe_dirs.extend(_candidate_windows_dll_dirs())

    seen: set[str] = set()
    for directory in probe_dirs:
        key = str(directory).lower()
        if key in seen:
            continue
        seen.add(key)
        dll_path = directory / "libgobject-2.0-0.dll"
        if dll_path.exists():
            return True
    return False


def _default_windows_weasyprint_cache_dir() -> Path:
    return Path.home() / ".weasyprint-windows" / "v68.1"


def _download_and_extract_windows_weasyprint(cache_dir: Path) -> Path:
    zip_url = os.getenv("WEASYPRINT_WINDOWS_ZIP_URL", DEFAULT_WEASYPRINT_WINDOWS_ZIP_URL).strip()
    zip_path = cache_dir.parent / "weasyprint-windows.zip"
    cache_dir.mkdir(parents=True, exist_ok=True)
    if not zip_path.exists() or zip_path.stat().st_size < 1_000_000:
        urllib.request.urlretrieve(zip_url, zip_path)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(cache_dir)
    return cache_dir


def _find_windows_weasyprint_exe() -> Path:
    configured_exe = os.getenv("WEASYPRINT_WINDOWS_EXE", "").strip()
    if configured_exe:
        path = Path(configured_exe)
        if path.exists():
            return path

    configured_cache_dir = os.getenv("WEASYPRINT_WINDOWS_CACHE_DIR", "").strip()
    cache_dir = Path(configured_cache_dir) if configured_cache_dir else _default_windows_weasyprint_cache_dir()
    if not cache_dir.exists():
        _download_and_extract_windows_weasyprint(cache_dir)
    exe_candidates = list(cache_dir.rglob("weasyprint.exe"))
    if exe_candidates:
        return exe_candidates[0]

    _download_and_extract_windows_weasyprint(cache_dir)
    exe_candidates = list(cache_dir.rglob("weasyprint.exe"))
    if exe_candidates:
        return exe_candidates[0]
    raise FileNotFoundError("Could not locate weasyprint.exe in Windows cache directory.")


def _font_css_path_for(html_path: Path) -> Path:
    css_path = html_path.with_name(f"{html_path.stem}.weasy-fonts.css")
    css_path.write_text(FONT_CSS_STRING, encoding="utf-8")
    return css_path


def _convert_with_windows_weasyprint_exe(html_path: Path, pdf_path: Path, font_css_path: Path) -> None:
    exe_path = _find_windows_weasyprint_exe()
    result = subprocess.run(
        [str(exe_path), "-s", str(font_css_path), str(html_path), str(pdf_path)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "WeasyPrint Windows executable failed. "
            f"stdout={result.stdout[-1000:] if result.stdout else ''} "
            f"stderr={result.stderr[-1000:] if result.stderr else ''}"
        )


def convert(html_path: Path, pdf_path: Path) -> None:
    if not html_path.exists():
        raise FileNotFoundError(f"HTML input not found: {html_path}")

    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    font_css_path = _font_css_path_for(html_path)
    added_dll_dirs = _configure_windows_dll_dirs()
    if os.name == "nt" and not _has_windows_gobject_dll(added_dll_dirs):
        _convert_with_windows_weasyprint_exe(html_path, pdf_path, font_css_path)
        return

    try:
        from weasyprint import CSS, HTML
    except Exception as exc:  # noqa: BLE001
        if os.name == "nt":
            try:
                _convert_with_windows_weasyprint_exe(html_path, pdf_path, font_css_path)
                return
            except Exception as exe_exc:  # noqa: BLE001
                raise RuntimeError(
                    "WeasyPrint failed to load native libraries. "
                    "Root cause: missing GTK/Pango runtime DLLs (notably libgobject-2.0-0). "
                    "Tried Python library mode and Windows standalone executable mode. "
                    f"DLL dirs searched: {added_dll_dirs if added_dll_dirs else 'none'}."
                ) from exe_exc
        raise RuntimeError(
            "WeasyPrint failed to load native libraries. "
            "Root cause: missing GTK/Pango runtime DLLs (notably libgobject-2.0-0). "
            "Install a GTK runtime and set WEASYPRINT_DLL_DIRECTORIES to its bin directory "
            f"(searched: {added_dll_dirs if added_dll_dirs else 'none'})."
        ) from exc

    font_css = CSS(string=FONT_CSS_STRING)

    html = HTML(filename=str(html_path))
    html.write_pdf(str(pdf_path), stylesheets=[font_css])


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert HTML digest to PDF via WeasyPrint.")
    parser.add_argument("input_html", type=Path)
    parser.add_argument("output_pdf", type=Path)
    args = parser.parse_args()
    convert(args.input_html, args.output_pdf)


if __name__ == "__main__":
    main()
