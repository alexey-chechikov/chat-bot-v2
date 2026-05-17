"""Cross-Claude sync check — what other Claudes did, what conflicts exist.

Runs from inside the bot7 git repo. Returns:
  - Remote branches list with recent commits
  - Files changed vs main on non-main branches
  - Local uncommitted changes that may conflict
  - Recommended action
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def find_repo() -> Path | None:
    """Look for bot7 git repo."""
    candidates = []
    env = os.environ.get("BOT7_PATH")
    if env:
        candidates.append(Path(env))
    candidates.extend([
        Path.home() / "code" / "bot7",
        Path("C:/bot7"),
        Path.cwd(),
    ])
    for p in candidates:
        if (p / ".git").exists():
            return p
    return None


def run_git(repo: Path, *args, timeout: int = 30) -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True, text=True, timeout=timeout,
        )
        if out.returncode != 0:
            return f"ERROR: {out.stderr.strip()}"
        return out.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return f"ERROR: {e}"


def fetch_remotes(repo: Path) -> str:
    return run_git(repo, "fetch", "--all", "--prune", timeout=120)


def list_remote_branches(repo: Path) -> list[str]:
    out = run_git(repo, "branch", "-r", "--format=%(refname:short)")
    if out.startswith("ERROR"):
        return []
    branches = [b.strip() for b in out.splitlines() if b.strip()]
    # exclude HEAD pointer
    return [b for b in branches if "HEAD" not in b]


def branch_summary(repo: Path, branch: str) -> dict:
    """Latest commits + files changed vs main."""
    commits_raw = run_git(repo, "log", "--oneline", "-5", branch)
    commits = commits_raw.splitlines() if not commits_raw.startswith("ERROR") else []

    # ahead/behind vs main
    rev_count = run_git(repo, "rev-list", "--left-right", "--count", f"origin/main...{branch}")
    behind, ahead = 0, 0
    if not rev_count.startswith("ERROR"):
        parts = rev_count.split()
        if len(parts) == 2:
            behind, ahead = int(parts[0]), int(parts[1])

    # changed files vs main
    diff = run_git(repo, "diff", "--name-only", f"origin/main...{branch}")
    changed = []
    if not diff.startswith("ERROR"):
        changed = [f for f in diff.splitlines() if f]

    return {
        "branch": branch,
        "ahead_of_main": ahead,
        "behind_main": behind,
        "recent_commits": commits,
        "files_changed_vs_main": changed[:30],  # cap to 30
        "files_changed_total": len(changed),
    }


def local_status(repo: Path) -> dict:
    branch = run_git(repo, "branch", "--show-current")
    status = run_git(repo, "status", "--short")
    uncommitted = [line for line in status.splitlines() if line.strip()]

    # ahead/behind upstream
    upstream = run_git(repo, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    behind, ahead = None, None
    if not upstream.startswith("ERROR"):
        rev_count = run_git(repo, "rev-list", "--left-right", "--count", f"{upstream}...HEAD")
        if not rev_count.startswith("ERROR"):
            parts = rev_count.split()
            if len(parts) == 2:
                behind, ahead = int(parts[0]), int(parts[1])

    return {
        "current_branch": branch,
        "upstream": upstream if not upstream.startswith("ERROR") else None,
        "ahead_of_upstream": ahead,
        "behind_upstream": behind,
        "uncommitted_files": uncommitted,
    }


def find_conflicts(repo: Path, local_files: list[str], other_branches: list[dict]) -> list[dict]:
    """Files modified locally AND in another branch vs main."""
    local_set = {f.split()[-1] for f in local_files if f.strip()}
    conflicts = []
    for b in other_branches:
        if b["branch"] in ("origin/main", "main"):
            continue
        overlap = set(b["files_changed_vs_main"]) & local_set
        if overlap:
            conflicts.append({"branch": b["branch"], "overlapping_files": sorted(overlap)})
    return conflicts


def recommend(local: dict, branches: list[dict], conflicts: list[dict]) -> list[str]:
    rec = []
    if local["uncommitted_files"]:
        rec.append(f"[!] {len(local['uncommitted_files'])} uncommitted files locally - commit or stash before merging anything")
    if conflicts:
        for c in conflicts:
            rec.append(f"[!] Conflict potential: {c['branch']} touches files you have modified ({len(c['overlapping_files'])} files)")
    # Find branches with commits to pull
    for b in branches:
        if b["branch"] in ("origin/main", "main"):
            continue
        if b["ahead_of_main"] > 0:
            rec.append(f"  -> {b['branch']}: {b['ahead_of_main']} commits ahead of main, {b['files_changed_total']} files changed. To inspect: `git diff main...{b['branch']}`")
    if not rec:
        rec.append("✅ No active branches with diff vs main, no local uncommitted changes")
    return rec


def main():
    repo = find_repo()
    if repo is None:
        print("ERROR: bot7 git repo not found")
        sys.exit(1)

    print(f"=== Cross-Claude sync check ===")
    print(f"Repo: {repo}")
    print(f"Generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    print()

    print("Fetching latest from remote...")
    fetch_result = fetch_remotes(repo)
    if fetch_result.startswith("ERROR"):
        print(f"  fetch failed: {fetch_result}")
    else:
        print("  ok")
    print()

    local = local_status(repo)
    print(f"Local branch: {local['current_branch']}")
    if local["upstream"]:
        print(f"  Upstream: {local['upstream']} (ahead {local['ahead_of_upstream']}, behind {local['behind_upstream']})")
    print(f"  Uncommitted: {len(local['uncommitted_files'])} files")
    if local["uncommitted_files"]:
        for f in local["uncommitted_files"][:10]:
            print(f"    {f}")
        if len(local["uncommitted_files"]) > 10:
            print(f"    ... ({len(local['uncommitted_files']) - 10} more)")
    print()

    print("Remote branches:")
    branches = list_remote_branches(repo)
    summaries = [branch_summary(repo, b) for b in branches]
    for s in summaries:
        if s["branch"] in ("origin/main",):
            print(f"  {s['branch']} (baseline)")
            continue
        print(f"  {s['branch']}: ahead={s['ahead_of_main']} files={s['files_changed_total']}")
        for c in s["recent_commits"][:3]:
            print(f"    | {c}")
    print()

    conflicts = find_conflicts(repo, local["uncommitted_files"], summaries)
    if conflicts:
        print("[!] POTENTIAL CONFLICTS:")
        for c in conflicts:
            print(f"  {c['branch']}: {len(c['overlapping_files'])} overlapping files")
            for f in c["overlapping_files"][:10]:
                print(f"    {f}")
        print()

    print("Recommendations:")
    for r in recommend(local, summaries, conflicts):
        print(f"  {r}")

    # JSON
    print()
    print("--- JSON ---")
    print(json.dumps({
        "repo": str(repo),
        "local": local,
        "branches": summaries,
        "conflicts": conflicts,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
