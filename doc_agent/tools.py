"""Tools for the doc agent.

Design: the doc has two kinds of blocks.
  <!-- AUTO:name -->       generated from code by analyzer.py on EVERY run (never by the LLM)
  <!-- NARRATIVE:name -->  prose written/updated by the LLM only when the change warrants it
Anything outside the blocks is yours and is never touched.
"""
import os
import pathlib
import re
import subprocess

from . import analyzer as az

DOC_PATH = os.getenv("DOC_PATH", "docs/DOCUMENTATION.md")
MAX_DIFF_CHARS = int(os.getenv("MAX_DIFF_CHARS", "60000"))
MAX_FILE_CHARS = 20000
CHANGELOG_ON = os.getenv("DOC_CHANGELOG", "").lower() in ("1", "true", "yes")
PENDING = "_Pending: the documentation agent will write this section._"
NARRATIVE = {"overview", "architecture_notes", "setup_usage"}

SECTIONS = [
    ("Overview", [("NARRATIVE", "overview")]),
    ("At a Glance", [("AUTO", "glance")]),
    ("Architecture", [("AUTO", "architecture"), ("NARRATIVE", "architecture_notes")]),
    ("Request Flows", [("AUTO", "flows")]),
    ("Project Structure", [("AUTO", "structure")]),
    ("API Reference", [("AUTO", "api")]),
    ("Modules", [("AUTO", "modules")]),
    ("Dependencies", [("AUTO", "dependencies")]),
    ("Configuration", [("AUTO", "env")]),
    ("Setup & Usage", [("NARRATIVE", "setup_usage")]),
    ("Tests", [("AUTO", "tests")]),
    ("Recent Changes", [("AUTO", "changelog")]),
]
HEADINGS = {name: h for h, blocks in SECTIONS for _, name in blocks}
_last_changes: list = []


# ───────────── block helpers ─────────────
def _block(kind, name, content):
    return f"<!-- {kind}:{name} -->\n{content}\n<!-- /{kind}:{name} -->\n"


def _rx(kind, name):
    return re.compile(rf"(<!-- {kind}:{name} -->\n)(.*?)(\n<!-- /{kind}:{name} -->)", re.S)


def _get_block(doc, kind, name):
    m = _rx(kind, name).search(doc)
    return m.group(2) if m else None


def _replace_block(doc, kind, name, content):
    rx = _rx(kind, name)
    if rx.search(doc):
        return rx.sub(lambda m: m.group(1) + content + m.group(3), doc, count=1)
    return doc.rstrip("\n") + f"\n\n## {HEADINGS[name]}\n\n" + _block(kind, name, content)


def _skeleton():
    name = os.getenv("GITHUB_REPOSITORY", "").split("/")[-1] or pathlib.Path.cwd().name
    parts = [f"# {name} — Documentation\n",
             "> Maintained by **doc-agent**. Content inside `AUTO:*` blocks is regenerated from the code on every "
             "push; `NARRATIVE:*` blocks are written by an AI agent. Add your own text anywhere outside these "
             "blocks and it will be preserved.\n"]
    for heading, blocks in SECTIONS:
        if heading == "Recent Changes" and not CHANGELOG_ON:
            continue
        parts.append(f"## {heading}\n")
        for kind, bname in blocks:
            parts.append(_block(kind, bname, PENDING if kind == "NARRATIVE" else ""))
    return "\n".join(parts)


def _read():
    p = pathlib.Path(DOC_PATH)
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _write(text):
    p = pathlib.Path(DOC_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


# ───────────── deterministic refresh (called by run_agent.py, not by the LLM) ─────────────
def refresh_auto_sections() -> str:
    """Regenerate every AUTO block (tree, API table, diagrams, modules, deps, env, tests) from the code."""
    global _last_changes
    original = _read()
    doc = original or _skeleton()
    a = az.analyze()
    changed = []
    for name, content in az.build_sections(a, changelog=CHANGELOG_ON).items():
        new = _replace_block(doc, "AUTO", name, content)
        if new != doc:
            changed.append(name)
            doc = new
    if doc != original:
        _write(doc)
    _last_changes = changed
    pending = [n for n in sorted(NARRATIVE) if (_get_block(doc, "NARRATIVE", n) or PENDING).strip() == PENDING]
    state = "Created" if not original else ("Updated" if doc != original else "Unchanged")
    return (f"{state} {DOC_PATH}. "
            f"AUTO sections changed: {changed or 'none'}. Pending narrative: {pending or 'none'}.")


# ───────────── tools exposed to the LLM ─────────────
def get_doc_status() -> dict:
    """Show which narrative sections are still pending and which AUTO sections just changed."""
    doc = _read()
    pending = [n for n in sorted(NARRATIVE) if (_get_block(doc, "NARRATIVE", n) or PENDING).strip() == PENDING]
    return {"doc_exists": bool(doc), "pending_narrative_sections": pending,
            "auto_sections_changed_this_run": _last_changes}


def get_repo_facts() -> str:
    """Return the auto-extracted facts (glance, API table, modules, env vars) to write accurate prose from."""
    s = az.build_sections(az.analyze())
    text = "\n\n".join(f"## {k}\n{s[k]}" for k in ("glance", "api", "modules", "env", "dependencies", "structure"))
    return text[:25000]


def read_doc() -> str:
    """Read the current documentation file."""
    return _read()


def get_git_diff() -> str:
    """Return the latest change as a git diff (docs/lockfiles excluded).
    Returns NO_RELEVANT_CHANGES, or DIFF_TOO_LARGE (meaning: rewrite all narrative sections)."""
    base = os.getenv("BASE_SHA", "")
    if not base or set(base) == {"0"}:
        base = "HEAD~1"
    rows = az._git("diff", "--name-status", base, "HEAD").splitlines()
    rows = [r for r in rows if not az.is_noise(r.split("\t")[-1])]
    if not rows:
        return "NO_RELEVANT_CHANGES"
    paths = [r.split("\t")[-1] for r in rows]
    diff = az._git("diff", "--unified=3", base, "HEAD", "--", *paths)
    header = "CHANGED FILES (A=added, M=modified, D=deleted, R=renamed):\n" + "\n".join(rows) + "\n\n"
    if len(diff) > MAX_DIFF_CHARS:
        return "DIFF_TOO_LARGE\n" + header
    return header + diff


def list_repo_files() -> list[str]:
    """List the source files in the repo (docs, lockfiles and tooling excluded)."""
    return az.list_files()


def read_file(path: str) -> str:
    """Read a file from the repo (first 20k characters)."""
    p = pathlib.Path(path).resolve()
    try:
        p.relative_to(pathlib.Path.cwd().resolve())
    except ValueError:
        return "ERROR: path outside repo"
    if not p.is_file():
        return f"ERROR: {path} not found (deleted or renamed?)"
    return p.read_text(errors="ignore")[:MAX_FILE_CHARS]


def set_narrative(section: str, markdown: str) -> str:
    """Write one narrative section. section must be one of: overview, architecture_notes, setup_usage.
    Use '###' or lower for any sub-headings. Do not include HTML comments."""
    if section not in NARRATIVE:
        return f"ERROR: section must be one of {sorted(NARRATIVE)}"
    text = re.sub(r"<!--.*?-->", "", markdown, flags=re.S).strip()
    if not text:
        return "ERROR: empty text"
    doc = _read() or _skeleton()
    _write(_replace_block(doc, "NARRATIVE", section, text))
    return f"updated narrative section '{section}'"


def convert_doc(fmt: str) -> str:
    """Convert the Markdown doc to pdf, docx or html using pandoc."""
    if fmt not in {"pdf", "docx", "html", "epub"}:
        return f"ERROR: unsupported format {fmt}"
    src = pathlib.Path(DOC_PATH)
    out = src.with_suffix(f".{fmt}")
    r = subprocess.run(["pandoc", str(src), "-o", str(out)], capture_output=True, text=True)
    return f"created {out}" if r.returncode == 0 else f"ERROR: {r.stderr[:500]}"
