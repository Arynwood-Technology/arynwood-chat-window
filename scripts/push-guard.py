#!/usr/bin/env python3
"""Refuse to let personal content leave this repo.

The public repo contains NO private terms — they live in a separate, private directory
(default ~/GitHub/arynwood-private, override with ARYNWOOD_PRIVATE_DIR):

    push-denylist.txt    case-insensitive regexes; a new commit that ADDS a matching line
                         (or whose message matches) is refused
    private-remotes.txt  substrings of remote URLs that are private; anything else is
                         treated as PUBLIC and checked strictly
    forbidden-paths.txt  (optional) regexes for paths that must never be committed

Fails CLOSED: if the private directory or denylist can't be read, nothing is allowed
through (bypass a deliberate exception with `git push --no-verify`).

Modes
    push-guard.py --hook REMOTE_NAME REMOTE_URL     git's pre-push contract (reads stdin)
    push-guard.py --range BASE..HEAD                scan commits in a range (dry run)
    push-guard.py --staged-against REF              scan the staged diff vs REF (pre-commit)
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ZERO = "0" * 40
# Only these refs may go to a public remote.
ALLOWED_PUBLIC_REFS = (re.compile(r"^refs/heads/main$"), re.compile(r"^refs/tags/v\d+\.\d+\.\d+"))
# Paths that must never appear in a commit bound for a public remote (generic ones; personal ones
# come from the private dir's forbidden-paths.txt so this file never names them).
FORBIDDEN_PATHS = [re.compile(p) for p in (
    r"personas\.local\.json$", r"(^|/)\.env$", r"\.db$",
    r"(^|/)mcp_servers\.json$", r"push-denylist", r"private-remotes", r"(^|/)arynwood-private/",
    # Where conversations and other owner data live: SQLite side files, the gateway's file
    # memory and overlay (IRC password), and what the app writes into a source checkout.
    r"\.db-(wal|shm|journal)$", r"\.sqlite3?$", r"(^|/)MEMORY\.md$", r"(^|/)memory/daily/",
    r"(^|/)gateway\.json$", r"(^|/)triggers/gpu_watch/", r"(^|/)static/social-media/",
    r"(^|/)music/assets/", r"(^|/)generated/(spreadsheets|images|audio)/",
)]


def git(*args: str, check: bool = True) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=check).stdout


def private_dir() -> Path:
    return Path(os.environ.get("ARYNWOOD_PRIVATE_DIR") or Path.home() / "GitHub" / "arynwood-private")


def read_patterns(name: str, required: bool = True) -> list[str]:
    path = private_dir() / name
    if not path.is_file():
        if not required:
            return []
        raise SystemExit(
            f"push-guard: cannot read {path} — refusing to proceed (fail closed).\n"
            f"Restore the private repo or set ARYNWOOD_PRIVATE_DIR; to bypass on purpose: git push --no-verify")
    return [ln.strip() for ln in path.read_text().splitlines() if ln.strip() and not ln.lstrip().startswith("#")]


def forbidden_paths() -> list[re.Pattern]:
    return FORBIDDEN_PATHS + [re.compile(p) for p in read_patterns("forbidden-paths.txt", required=False)]


def scan_commit(sha: str, denylist: list[re.Pattern]) -> list[str]:
    findings = []
    forbidden = forbidden_paths()
    short = sha[:9]
    message = git("log", "-1", "--format=%B", sha)
    for rx in denylist:
        if rx.search(message):
            findings.append(f"{short}: commit MESSAGE matches /{rx.pattern}/")
    for path in git("diff-tree", "--no-commit-id", "--name-only", "-r", "--root", "--diff-filter=AM", sha).splitlines():
        if any(f.search(path) for f in forbidden):
            findings.append(f"{short}: forbidden path {path}")
    findings += scan_diff(git("show", "--format=", "-U0", "--no-color", sha), denylist, short)
    return findings


def scan_diff(diff: str, denylist: list[re.Pattern], label: str) -> list[str]:
    findings, current = [], "?"
    for line in diff.splitlines():
        if line.startswith("+++ "):
            current = line[6:] if line.startswith("+++ b/") else line[4:]
        elif line.startswith("+") and not line.startswith("+++"):
            for rx in denylist:
                if rx.search(line):
                    findings.append(f"{label}: {current}: added line matches /{rx.pattern}/ -> {line[1:].strip()[:100]}")
                    break
    return findings


def compile_denylist() -> list[re.Pattern]:
    return [re.compile(p, re.IGNORECASE) for p in read_patterns("push-denylist.txt")]


def is_private_remote(url: str) -> bool:
    return any(marker in url for marker in read_patterns("private-remotes.txt"))


def report(findings: list[str]) -> int:
    if not findings:
        print("push-guard: clean — nothing personal in what would be pushed.")
        return 0
    print("push-guard: REFUSING — personal content found:\n", file=sys.stderr)
    for f in findings[:40]:
        print(f"  {f}", file=sys.stderr)
    if len(findings) > 40:
        print(f"  … and {len(findings) - 40} more", file=sys.stderr)
    print("\nFix the commit(s) and retry. Only if this is intentional: git push --no-verify", file=sys.stderr)
    return 1


def run_hook(remote_name: str, remote_url: str) -> int:
    denylist = compile_denylist()
    if is_private_remote(remote_url):
        return 0                                    # private remote: nothing to protect
    findings: list[str] = []
    for raw in sys.stdin.read().splitlines():
        local_ref, local_sha, remote_ref, remote_sha = raw.split()
        if local_sha == ZERO:
            continue                                # a delete carries no content
        if not any(rx.match(remote_ref) for rx in ALLOWED_PUBLIC_REFS):
            findings.append(f"{remote_ref}: only main and v*.*.* tags may be pushed to a public remote ({local_ref})")
            continue
        exclude = [remote_sha] if remote_sha != ZERO else [f"--remotes={remote_name}"]
        for sha in git("rev-list", local_sha, "--not", *exclude).split():
            findings += scan_commit(sha, denylist)
    return report(findings)


def main(argv: list[str]) -> int:
    if len(argv) >= 4 and argv[1] == "--hook":
        return run_hook(argv[2], argv[3])
    if len(argv) == 3 and argv[1] == "--range":
        denylist = compile_denylist()
        return report([f for sha in git("rev-list", argv[2]).split() for f in scan_commit(sha, denylist)])
    if len(argv) == 3 and argv[1] == "--staged-against":
        denylist = compile_denylist()
        findings = scan_diff(git("diff", "--cached", "-U0", "--no-color", argv[2]), denylist, "staged")
        forbidden = forbidden_paths()
        for path in git("diff", "--cached", "--name-only", "--diff-filter=AM", argv[2]).splitlines():
            if any(f.search(path) for f in forbidden):
                findings.append(f"staged: forbidden path {path}")
        return report(findings)
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
