#!/usr/bin/env python3
"""Check a Codex Skill directory for common publication hazards."""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path


BLOCKED_DIRS = {".git", "__pycache__", "node_modules", ".venv", "dist", "build"}
BLOCKED_NAMES = {".DS_Store", "id_rsa", "id_ed25519"}
BLOCKED_SUFFIXES = {".pem", ".p12", ".pfx", ".key"}
MAX_FILE_BYTES = 20 * 1024 * 1024

# Split sensitive prefixes so this source file does not flag itself.
SECRET_PATTERNS = {
    "private key": re.compile("BEGIN " + r"(?:RSA |EC |OPENSSH )?PRIVATE KEY"),
    "GitHub token": re.compile(r"(?:gh[pousr]_)[A-Za-z0-9]{20,}|(?:github_pat_)[A-Za-z0-9_]{20,}"),
    "AWS access key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "Slack token": re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    "generic assigned secret": re.compile(
        r"(?i)(?:api[_-]?key|access[_-]?token|client[_-]?secret|password)\s*[:=]\s*['\"]?[A-Za-z0-9_./+=-]{12,}"
    ),
}


def is_env_file(path: Path) -> bool:
    return path.name == ".env" or path.name.startswith(".env.")


def scan(skill_dir: Path) -> list[tuple[str, str]]:
    findings: list[tuple[str, str]] = []
    this_file = Path(__file__).resolve()

    for root, dirs, files in os.walk(skill_dir):
        root_path = Path(root)
        for dirname in list(dirs):
            if dirname in BLOCKED_DIRS:
                findings.append((str((root_path / dirname).relative_to(skill_dir)), "blocked directory"))
                dirs.remove(dirname)

        for filename in files:
            path = root_path / filename
            rel = str(path.relative_to(skill_dir))
            if path.resolve() == this_file:
                continue
            if filename in BLOCKED_NAMES or is_env_file(path) or path.suffix.lower() in BLOCKED_SUFFIXES:
                findings.append((rel, "blocked file type"))
                continue
            try:
                size = path.stat().st_size
            except OSError:
                findings.append((rel, "unreadable file"))
                continue
            if size > MAX_FILE_BYTES:
                findings.append((rel, "file larger than 20 MiB"))
                continue
            try:
                data = path.read_bytes()
            except OSError:
                findings.append((rel, "unreadable file"))
                continue
            if b"\x00" in data:
                continue
            text = data.decode("utf-8", errors="ignore")
            for category, pattern in SECRET_PATTERNS.items():
                if pattern.search(text):
                    findings.append((rel, f"possible {category}"))

    return sorted(set(findings))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("skill_dir", type=Path)
    args = parser.parse_args()
    skill_dir = args.skill_dir.expanduser().resolve()

    if not skill_dir.is_dir():
        print(f"ERROR: not a directory: {skill_dir}", file=sys.stderr)
        return 2
    if not (skill_dir / "SKILL.md").is_file():
        print(f"ERROR: SKILL.md not found in {skill_dir}", file=sys.stderr)
        return 2

    findings = scan(skill_dir)
    if findings:
        print("Preflight blocked:")
        for path, category in findings:
            print(f"- {path}: {category}")
        return 1

    print(f"Preflight passed: {skill_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
