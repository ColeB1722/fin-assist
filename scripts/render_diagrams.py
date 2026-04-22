#!/usr/bin/env python3
"""Render Mermaid diagrams from README.md to SVG + PNG.

The README is the single source of truth. Each ```mermaid fenced block is
preceded by an HTML comment of the form `<!-- diagram:<slug> -->` which
names the output file (e.g. `docs/diagrams/<slug>.svg`).

Usage: python scripts/render_diagrams.py [README_PATH] [OUT_DIR]
Defaults: README.md, docs/diagrams/

Exit codes:
    0  all diagrams rendered
    1  parse / render error
    2  mmdc not on PATH
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

MARKER_RE = re.compile(
    r"<!--\s*diagram:([A-Za-z0-9_\-]+)\s*-->\s*\n```mermaid\n(.*?)\n```",
    re.DOTALL,
)


def extract_diagrams(readme: Path) -> list[tuple[str, str]]:
    """Return [(slug, source), ...] for each marked mermaid block."""
    text = readme.read_text(encoding="utf-8")
    return [(m.group(1), m.group(2)) for m in MARKER_RE.finditer(text)]


def render(slug: str, source: str, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".mmd", delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write(source)
        tmp_path = Path(tmp.name)

    try:
        svg = out_dir / f"{slug}.svg"
        png = out_dir / f"{slug}.png"
        # SVG: canonical, transparent background, scales cleanly.
        subprocess.run(
            ["mmdc", "-i", str(tmp_path), "-o", str(svg), "-b", "transparent", "-q"],
            check=True,
        )
        # PNG: high-res preview for tools that need raster.
        subprocess.run(
            ["mmdc", "-i", str(tmp_path), "-o", str(png), "-b", "white", "-w", "2400", "-q"],
            check=True,
        )
        print(f"  {slug}: {svg} + {png.name}")
    finally:
        tmp_path.unlink(missing_ok=True)


def main(argv: list[str]) -> int:
    readme = Path(argv[1]) if len(argv) > 1 else Path("README.md")
    out_dir = Path(argv[2]) if len(argv) > 2 else Path("docs/diagrams")

    if shutil.which("mmdc") is None:
        print("error: mmdc not found on PATH (install @mermaid-js/mermaid-cli)", file=sys.stderr)
        return 2

    if not readme.is_file():
        print(f"error: {readme} not found", file=sys.stderr)
        return 1

    diagrams = extract_diagrams(readme)
    if not diagrams:
        print(f"warning: no marked mermaid blocks found in {readme}", file=sys.stderr)
        print("hint: each block must be preceded by `<!-- diagram:<slug> -->`", file=sys.stderr)
        return 1

    seen: set[str] = set()
    for slug, _ in diagrams:
        if slug in seen:
            print(f"error: duplicate diagram slug {slug!r}", file=sys.stderr)
            return 1
        seen.add(slug)

    print(f"rendering {len(diagrams)} diagram(s) from {readme} → {out_dir}/")
    for slug, source in diagrams:
        try:
            render(slug, source, out_dir)
        except subprocess.CalledProcessError as e:
            print(f"error rendering {slug}: mmdc exit {e.returncode}", file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
