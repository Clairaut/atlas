# Standard Modules
from dataclasses import dataclass, field
from pathlib import Path
from datetime import date, datetime
import json


# A single journal record — text renders to markdown, data carries the structured fields for JSON export
@dataclass
class JournalEntry:
    text: str
    data: dict = field(default_factory=dict)


# Return today's markdown journal path, creating the file with a date heading if missing
def _md_path(journal_dir: Path) -> Path:
    journal_dir.mkdir(parents=True, exist_ok=True)
    path = journal_dir / f"{date.today().isoformat()}.md"
    if not path.exists():
        path.write_text(f"# {date.today().isoformat()}\n")
    return path


# Return today's JSON journal path (file itself is created on first append)
def _json_path(journal_dir: Path) -> Path:
    journal_dir.mkdir(parents=True, exist_ok=True)
    return journal_dir / f"{date.today().isoformat()}.json"


# Load today's JSON journal document, creating a fresh skeleton if missing or unreadable
def _load_json(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            pass
    return {"date": date.today().isoformat(), "sections": []}


# Append a markdown section: "## {title} — {HH:MM}" followed by "- {entry.text}" bullets
def _append_md(journal_dir: Path, title: str, entries: list) -> Path:
    path = _md_path(journal_dir)
    timestamp = datetime.now().strftime("%H:%M")
    body = "\n".join(f"- {e.text}" for e in entries)
    with path.open("a") as f:
        f.write(f"\n## {title} — {timestamp}\n\n{body}\n")
    return path


# Append a JSON section: entries are just their structured `data` fields — `text` is a
# markdown-rendering concern only, not duplicated into the machine-readable export
def _append_json(journal_dir: Path, title: str, entries: list) -> Path:
    path = _json_path(journal_dir)
    doc  = _load_json(path)
    doc["sections"].append({
        "title": title,
        "time": datetime.now().strftime("%H:%M"),
        "entries": [dict(e.data) for e in entries],
    })
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    return path


# Append a titled, timestamped section to today's journal entry in the requested format —
# multiple sections per title stay distinct since each call is stamped independently,
# so other tools can append their own sections without stepping on each other
def export_section(journal_dir: Path, title: str, entries: list, fmt: str = "md") -> Path:
    if fmt == "json":
        return _append_json(journal_dir, title, entries)
    return _append_md(journal_dir, title, entries)
