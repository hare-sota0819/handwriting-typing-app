"""Export a clean, public copy of this repository (no private handwriting).

The development checkout carries the author's own glyph stores, scans, paper
and course material; none of that belongs in the public repo (and a public
repo must not carry it in its HISTORY either). This copies the git-tracked
tree minus the private paths into a fresh directory, ready for `git init` +
first commit. Run verify.sh there before publishing.

    python scripts/export_public.py ../handwriting-converter
"""

import argparse
import fnmatch
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Private / development-only paths (fnmatch patterns against repo-relative
# POSIX paths). Everything else that git tracks is public.
EXCLUDE = [
    "glyphs/*",                 # every checked-in handwriting store
    "scans/*",
    "archive/*",
    "docs/PROMPT.md", "docs/STATUS.md", "docs/SOLVED.md", "docs/BUGS.md",
    "docs/DECISIONS.md", "docs/superpowers/*",
    "samples/thermo_test.docx",  # course material dropped in as a test input
    "template/ipad_pilot/*", "template/rewrite/*", "template/sqrt_rewrite/*",
    "scripts/make_template_rewrite.py", "scripts/make_template_sqrt.py",
    "scripts/normalize_weight.py", "scripts/reseat_store.py",
    "packaging/app_name.local.txt", "packaging/app_icon.local.*",
]


def tracked_files() -> list[str]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, check=True,
                         capture_output=True).stdout
    return [p for p in out.decode("utf-8").split("\0") if p]


def is_excluded(rel: str) -> bool:
    return any(fnmatch.fnmatch(rel, pat) for pat in EXCLUDE)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("dest", type=Path)
    ap.add_argument("--force", action="store_true", help="wipe dest first")
    args = ap.parse_args(argv)
    dest = args.dest.resolve()
    if dest.exists():
        if not args.force or not dest.is_dir():
            print(f"refusing: {dest} exists (use --force to wipe it)", file=sys.stderr)
            return 1
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    kept = skipped = 0
    for rel in tracked_files():
        if is_excluded(rel):
            skipped += 1
            continue
        src = ROOT / rel
        if not src.exists():
            continue
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
        kept += 1
    print(f"exported {kept} files to {dest} ({skipped} private/dev files left out)")
    print("next: cd there; python3 -m venv .venv && .venv/bin/pip install -r "
          "requirements.txt; ./scripts/verify.sh; git init && git add -A && git commit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
