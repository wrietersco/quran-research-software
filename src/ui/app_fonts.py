"""Download OFL Arabic fonts (Amiri, Noto Naskh Arabic) and register for Tk + Matplotlib."""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

# google/fonts OFL — stable raw URLs
_FONT_SPECS: tuple[tuple[str, str], ...] = (
    (
        "Amiri-Regular.ttf",
        "https://raw.githubusercontent.com/google/fonts/main/ofl/amiri/Amiri-Regular.ttf",
    ),
    (
        # Variable font (wght axis); OFL from google/fonts
        "NotoNaskhArabic-wght.ttf",
        "https://raw.githubusercontent.com/google/fonts/main/ofl/notonaskharabic/NotoNaskhArabic%5Bwght%5D.ttf",
    ),
)

_USER_AGENT = (
    "Mozilla/5.0 (compatible; QuranLexicon/1.0; +https://github.com/google/fonts)"
)


def font_assets_dir(project_root: Path) -> Path:
    return project_root / "assets" / "fonts"


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = resp.read()
    if len(data) < 1024:
        raise OSError(f"Download too small from {url}")
    dest.write_bytes(data)


def _register_windows_private_fonts(paths: list[Path]) -> None:
    import ctypes

    FR_PRIVATE = 0x10
    gdi32 = ctypes.windll.gdi32
    for p in paths:
        w = str(p.resolve())
        if gdi32.AddFontResourceExW(w, FR_PRIVATE, 0) == 0:
            print(f"Warning: AddFontResourceEx failed for {p}", file=sys.stderr)


def _register_unix_fonts(paths: list[Path]) -> None:
    system = platform.system()
    if system == "Darwin":
        dest_dir = Path.home() / "Library" / "Fonts"
    else:
        dest_dir = Path.home() / ".local" / "share" / "fonts" / "quran-lexicon-ui"
    dest_dir.mkdir(parents=True, exist_ok=True)
    for p in paths:
        dest = dest_dir / p.name
        try:
            if not dest.is_file() or dest.stat().st_size != p.stat().st_size:
                shutil.copy2(p, dest)
        except OSError as e:
            print(f"Warning: could not install font {p.name}: {e}", file=sys.stderr)
    if system != "Darwin":
        try:
            subprocess.run(
                ["fc-cache", "-f", str(dest_dir)],
                capture_output=True,
                timeout=120,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            print(f"Warning: fc-cache: {e}", file=sys.stderr)


def _register_matplotlib_fonts(paths: list[Path]) -> None:
    try:
        from matplotlib import font_manager
    except ImportError:
        return
    for p in paths:
        try:
            font_manager.fontManager.addfont(str(p.resolve()))
        except (OSError, ValueError) as e:
            print(f"Warning: matplotlib addfont {p}: {e}", file=sys.stderr)


def _family_name_from_file(path: Path) -> str:
    try:
        from matplotlib.font_manager import FontProperties

        return FontProperties(fname=str(path.resolve())).get_name()
    except Exception:
        return path.stem.replace("-", " ")


def ensure_ui_fonts_ready(project_root: Path) -> tuple[str, str]:
    """
    Ensure font files exist, register with OS (where possible) and Matplotlib.
    Returns (arabic_family, latin_heading_family) for Tk styles.
    """
    sysname = platform.system()
    if sysname == "Windows":
        latin = "Segoe UI"
    elif sysname == "Darwin":
        latin = "Helvetica Neue"
    else:
        latin = "DejaVu Sans"
    d = font_assets_dir(project_root)
    paths: list[Path] = []
    for fname, url in _FONT_SPECS:
        dest = d / fname
        if not dest.is_file() or dest.stat().st_size < 1024:
            try:
                _download(url, dest)
            except Exception as e:
                print(f"Warning: font download failed ({fname}): {e}", file=sys.stderr)
                continue
        paths.append(dest)

    if not paths:
        if platform.system() == "Windows":
            return "Segoe UI", latin
        return "DejaVu Sans", latin

    if platform.system() == "Windows":
        _register_windows_private_fonts(paths)
    elif platform.system() in ("Linux", "Darwin"):
        _register_unix_fonts(paths)

    _register_matplotlib_fonts(paths)

    arabic = _family_name_from_file(paths[0])
    return arabic, latin
