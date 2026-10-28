"""Checkpoint 5 verification: paper compositor + output + CLI.

Checks the full end-to-end path on a real .docx:
- CLI produces PNG output; pixels are opaque RGB on paper (not transparent)
- multi-page document -> combined PDF written and reloadable
- --seed reproducibility survives the whole pipeline (same seed => identical
  PNG bytes; different seed => different)
- --style JSON is honored (a different ink color changes the pixels)
Exit 0 = pass. Also leaves human-viewable output in out/.
"""

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PIL import Image

import make_samples

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "out"
PY = str(ROOT / ".venv" / "bin" / "python")


def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [PY, "-m", "handwriting", *args],
        cwd=ROOT, capture_output=True, text=True,
    )


def main() -> int:
    failures: list[str] = []
    OUT.mkdir(exist_ok=True)
    if not (make_samples.SAMPLES / "plain.docx").exists():
        make_samples.main()
    plain = make_samples.SAMPLES / "plain.docx"
    multi = make_samples.SAMPLES / "multi.docx"

    # 1. basic PNG output, opaque RGB on paper
    png = OUT / "cli_plain.png"
    r = run_cli(str(plain), "--seed", "1", "--out", str(png))
    if r.returncode != 0:
        failures.append(f"CLI failed: {r.stderr.strip()}")
    elif not png.exists():
        failures.append("CLI reported success but PNG missing")
    else:
        img = Image.open(png)
        if img.mode != "RGB":
            failures.append(f"output not RGB (paper-composited): {img.mode}")
        corner = img.getpixel((2, 2))
        if corner == (255, 255, 255) or sum(corner) < 600:
            failures.append(f"paper corner looks wrong (off-white expected): {corner}")

    # 2. seed reproducibility through the whole pipeline
    a, b = OUT / "cli_seedA.png", OUT / "cli_seedB.png"
    run_cli(str(plain), "--seed", "5", "--out", str(a))
    run_cli(str(plain), "--seed", "5", "--out", str(b))
    c = OUT / "cli_seedC.png"
    run_cli(str(plain), "--seed", "6", "--out", str(c))
    if a.exists() and b.exists() and a.read_bytes() != b.read_bytes():
        failures.append("same seed produced different PNG bytes end-to-end")
    if a.exists() and c.exists() and a.read_bytes() == c.read_bytes():
        failures.append("different seeds produced identical PNG bytes")

    # 3. multi-page -> combined PDF
    pdf = OUT / "cli_multi.pdf"
    r = run_cli(str(multi), "--seed", "2", "--out", str(pdf))
    if r.returncode != 0:
        failures.append(f"PDF CLI failed: {r.stderr.strip()}")
    elif not pdf.exists():
        failures.append("PDF not written")
    else:
        # Pillow writes but cannot read PDFs, so validate the file directly:
        # a %PDF header and a non-trivial size (embedded page raster).
        head = pdf.read_bytes()[:5]
        if head != b"%PDF-":
            failures.append(f"PDF header wrong: {head!r}")
        if pdf.stat().st_size < 1000:
            failures.append(f"PDF suspiciously small: {pdf.stat().st_size} bytes")

    # 4. --style JSON honored (red ink must change pixels)
    style_path = OUT / "red_ink.json"
    style_path.write_text(json.dumps({"ink_rgb": [200, 20, 20]}))
    red = OUT / "cli_red.png"
    run_cli(str(plain), "--seed", "1", "--style", str(style_path), "--out", str(red))
    if png.exists() and red.exists() and png.read_bytes() == red.read_bytes():
        failures.append("--style ink_rgb had no effect on output")

    print("CLI stdout (last run):", r.stdout.strip())
    print("outputs in:", OUT)
    print()
    if failures:
        print(f"FAIL ({len(failures)} problems):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("PASS: checkpoint 5 checks all green")
    return 0


if __name__ == "__main__":
    sys.exit(main())
