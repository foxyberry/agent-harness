#!/usr/bin/env python3
"""
merge-cleanup — PR merge/close 이후 사람이 하던 정리 후보를 advisory 로 모아 보여준다.

파괴적 작업은 하지 않는다. git fetch 외에는 브랜치 삭제, 이슈 close, worktree remove 를
실행하지 않고 후보 명령만 출력한다.
"""
import argparse
import json
import os
import shlex
import subprocess


def _run(cmd, cwd, timeout=10):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)


def _out(cmd, cwd, timeout=10):
    r = _run(cmd, cwd, timeout=timeout)
    if r.returncode != 0:
        return None
    return r.stdout.strip()


def _git_root(project_dir):
    root = _out(["git", "rev-parse", "--show-toplevel"], project_dir)
    return root or project_dir


def _repo(project_dir, explicit=None):
    if explicit:
        return explicit
    data = _out(["gh", "repo", "view", "--json", "nameWithOwner"], project_dir)
    if not data:
        return None
    try:
        return json.loads(data).get("nameWithOwner")
    except Exception:
        return None


def _repo_view_cmd(repo, fields):
    cmd = ["gh", "repo", "view"]
    if repo:
        cmd.append(repo)
    cmd.extend(["--json", fields])
    return cmd


def _pr_list_cmd(repo, state, limit):
    cmd = [
        "gh", "pr", "list",
        "--state", state,
        "--limit", str(limit),
        "--json",
        "number,title,url,mergedAt,closedAt,headRefName,isCrossRepository,closingIssuesReferences",
    ]
    if repo:
        cmd.extend(["--repo", repo])
    return cmd


def _default_branch(project_dir, repo=None):
    data = _out(_repo_view_cmd(repo, "defaultBranchRef"), project_dir)
    if data:
        try:
            name = (json.loads(data).get("defaultBranchRef") or {}).get("name")
            if name:
                return name
        except Exception:
            pass
    ref = _out(["git", "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"], project_dir)
    if ref and ref.startswith("origin/"):
        return ref.split("/", 1)[1]
    return "main"


def _current_branch(project_dir):
    return _out(["git", "branch", "--show-current"], project_dir) or ""


def _sync_status(project_dir, branch):
    local = _out(["git", "rev-parse", "--verify", branch], project_dir)
    remote_ref = f"origin/{branch}"
    remote = _out(["git", "rev-parse", "--verify", remote_ref], project_dir)
    if not local or not remote:
        return {"branch": branch, "status": "unknown", "message": "local or origin branch not found"}
    counts = _out(["git", "rev-list", "--left-right", "--count", f"{branch}...{remote_ref}"], project_dir)
    if not counts:
        return {"branch": branch, "status": "unknown", "message": "cannot compare local and origin"}
    ahead, behind = [int(x) for x in counts.split()]
    ff = _run(["git", "merge-base", "--is-ancestor", branch, remote_ref], project_dir).returncode == 0
    return {"branch": branch, "ahead": ahead, "behind": behind, "fast_forward": ff}


def _merged_local_branches(project_dir, base_ref, protected_base):
    raw = _out(["git", "branch", "--merged", base_ref, "--format", "%(refname:short)"], project_dir)
    if raw is None:
        return []
    current = _current_branch(project_dir)
    protected = {protected_base, current, "main", "master", "develop"}
    return [b for b in raw.splitlines() if b and b not in protected]


def _local_branches(project_dir):
    raw = _out(["git", "branch", "--format", "%(refname:short)"], project_dir)
    if raw is None:
        return set()
    return {b for b in raw.splitlines() if b}


def _local_branch_candidates(project_dir, repo, base_ref, protected_base, recent_limit):
    current = _current_branch(project_dir)
    protected = {protected_base, current, "main", "master", "develop"}
    existing = _local_branches(project_dir) - protected
    candidates = {
        branch: {
            "branch": branch,
            "reason": "ancestor",
            "force": False,
            "pr": None,
            "state": "",
            "url": "",
        }
        for branch in _merged_local_branches(project_dir, base_ref, protected_base)
    }

    prs = _recent_prs(project_dir, repo, "merged", recent_limit)
    prs += _recent_prs(project_dir, repo, "closed", recent_limit)
    for pr in prs:
        if pr.get("isCrossRepository"):
            continue
        branch = pr.get("headRefName")
        if not branch or branch not in existing or branch in candidates:
            continue
        candidates[branch] = {
            "branch": branch,
            "reason": "pr",
            "force": True,
            "pr": pr.get("number"),
            "state": "merged" if pr.get("mergedAt") else "closed",
            "url": pr.get("url") or "",
        }
    return sorted(candidates.values(), key=lambda c: c["branch"])


def _remote_branches(project_dir, remote="origin"):
    raw = _out(
        ["git", "for-each-ref", "--format", "%(refname:short)", f"refs/remotes/{remote}"],
        project_dir,
    )
    if raw is None:
        return set()
    return {b.split("/", 1)[1] for b in raw.splitlines() if "/" in b and not b.endswith("/HEAD")}


def _recent_prs(project_dir, repo, state, limit):
    data = _out(_pr_list_cmd(repo, state, limit), project_dir, timeout=15)
    if not data:
        return []
    try:
        rows = json.loads(data)
        return rows if isinstance(rows, list) else []
    except Exception:
        return []


def _remote_branch_candidates(project_dir, repo, recent_limit):
    existing = _remote_branches(project_dir)
    candidates = []
    prs = _recent_prs(project_dir, repo, "merged", recent_limit)
    prs += _recent_prs(project_dir, repo, "closed", recent_limit)
    for pr in prs:
        if pr.get("isCrossRepository"):
            continue
        head = pr.get("headRefName")
        if head and head in existing:
            candidates.append({
                "branch": head,
                "pr": pr.get("number"),
                "state": "merged" if pr.get("mergedAt") else "closed",
                "title": pr.get("title") or "",
                "url": pr.get("url") or "",
            })
    seen = set()
    out = []
    for c in candidates:
        key = (c["branch"], c["pr"])
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out


def _closing_issue_candidates(project_dir, repo, recent_limit):
    rows = []
    for pr in _recent_prs(project_dir, repo, "merged", recent_limit):
        issues = pr.get("closingIssuesReferences") or []
        if not issues:
            continue
        rows.append({
            "pr": pr.get("number"),
            "title": pr.get("title") or "",
            "url": pr.get("url") or "",
            "merged_at": pr.get("mergedAt") or "",
            "issues": [
                {"number": i.get("number"), "url": i.get("url") or ""}
                for i in issues if isinstance(i, dict)
            ],
        })
    return rows


def _worktrees(project_dir, merged_local):
    raw = _out(["git", "worktree", "list", "--porcelain"], project_dir)
    if raw is None:
        return []
    records = []
    cur = {}
    for line in raw.splitlines() + [""]:
        if not line:
            if cur:
                records.append(cur)
                cur = {}
            continue
        key, _, val = line.partition(" ")
        cur[key] = val
    merged = set(merged_local)
    out = []
    for r in records:
        branch_ref = r.get("branch", "")
        branch = branch_ref.replace("refs/heads/", "") if branch_ref else ""
        if branch and branch in merged:
            out.append({"path": r.get("worktree", ""), "branch": branch})
    return out


def _untracked(project_dir):
    raw = _out(["git", "status", "--short"], project_dir)
    if raw is None:
        return []
    return [line[3:] for line in raw.splitlines() if line.startswith("?? ")]


def collect(project_dir, repo=None, recent_limit=20, fetch=True):
    root = _git_root(project_dir)
    resolved_repo = _repo(root, repo)
    cwd_repo = _repo(root)
    fetch_result = {"ran": False, "ok": None}
    if fetch:
        r = _run(["git", "fetch", "origin"], root, timeout=30)
        fetch_result = {"ran": True, "ok": r.returncode == 0}
    default = _default_branch(root, resolved_repo)
    cleanup_base_ref = f"origin/{default}"
    sync = _sync_status(root, default)
    local_candidates = _local_branch_candidates(
        root, resolved_repo, cleanup_base_ref, default, recent_limit
    )
    local = [candidate["branch"] for candidate in local_candidates]
    remote = _remote_branch_candidates(root, resolved_repo, recent_limit)
    issues = _closing_issue_candidates(root, resolved_repo, recent_limit)
    wts = _worktrees(root, local)
    untracked = _untracked(root)
    return {
        "project_dir": root,
        "repo": resolved_repo,
        "local_repo": cwd_repo,
        "repo_mismatch": bool(repo and cwd_repo and repo != cwd_repo),
        "fetch": fetch_result,
        "default_branch": default,
        "cleanup_base_ref": cleanup_base_ref,
        "sync": sync,
        "local_merged_branches": local,
        "local_branch_candidates": local_candidates,
        "remote_branch_candidates": remote,
        "closing_issue_candidates": issues,
        "worktree_candidates": wts,
        "untracked": untracked,
        "memory_update_reminder": True,
    }


def render(result):
    lines = []
    repo = result.get("repo") or "(unknown repo)"
    default = result["default_branch"]
    lines.append(f"merge-cleanup 리포트 — {repo}")
    lines.append(f"project: {result['project_dir']}")
    lines.append("advisory-only: 삭제/close/remove 는 자동 실행하지 않음")
    if result.get("repo_mismatch"):
        lines.append(
            f"⚠ --repo({repo}) 와 현재 git remote({result.get('local_repo')}) 가 다름 — "
            "GitHub PR/이슈 조회와 로컬 git 후보가 다른 저장소 기준일 수 있음"
        )
    fetch = result.get("fetch") or {}
    if fetch.get("ran") and fetch.get("ok") is False:
        lines.append("⚠ git fetch origin 실패 — 원격 기준 후보가 오래됐을 수 있음")
    lines.append("")

    sync = result["sync"]
    lines.append(f"■ 기본 브랜치 동기화 — {default}")
    if sync.get("status") == "unknown":
        lines.append(f"  확인 불가: {sync.get('message')}")
    elif sync.get("behind", 0) == 0 and sync.get("ahead", 0) == 0:
        lines.append("  local == origin")
    else:
        lines.append(f"  ahead {sync.get('ahead')} · behind {sync.get('behind')}")
        if sync.get("fast_forward"):
            lines.append(
                f"  후보 명령: git switch {shlex.quote(default)} "
                f"&& git merge --ff-only {shlex.quote('origin/' + default)}"
            )
        else:
            lines.append("  fast-forward 불가 — 사람이 히스토리 확인 필요")
    lines.append("")

    cleanup_base = result.get("cleanup_base_ref", f"origin/{default}")
    lines.append(
        f"■ 로컬 정리 브랜치 삭제 후보 ({len(result['local_merged_branches'])}) "
        f"— 기준 {cleanup_base}"
    )
    if result["local_merged_branches"]:
        candidates = result.get("local_branch_candidates") or [
            {"branch": b, "force": False} for b in result["local_merged_branches"]
        ]
        for candidate in candidates:
            branch = candidate["branch"]
            if candidate.get("force"):
                lines.append(
                    f"  {branch}  ← PR #{candidate.get('pr')} {candidate.get('state')}  "
                    f"{candidate.get('url') or ''}".rstrip()
                )
                lines.append(
                    f"       후보 명령: git branch -D {shlex.quote(branch)} "
                    "(squash/closed PR은 git ancestry에 없어 -d가 거부할 수 있음)"
                )
            else:
                lines.append(f"  {branch}  → 후보 명령: git branch -d {shlex.quote(branch)}")
    else:
        lines.append("  (없음)")
    lines.append("")

    lines.append(f"■ 원격 브랜치 삭제 후보 ({len(result['remote_branch_candidates'])})")
    if result["remote_branch_candidates"]:
        for c in result["remote_branch_candidates"]:
            lines.append(
                f"  origin/{c['branch']}  ← PR #{c['pr']} {c['state']}  {c['url']}"
            )
            lines.append(f"       후보 명령: git push origin --delete {shlex.quote(c['branch'])}")
    else:
        lines.append("  (없음)")
    lines.append("")

    lines.append(f"■ 관련 이슈 close 확인 후보 ({len(result['closing_issue_candidates'])})")
    if result["closing_issue_candidates"]:
        for pr in result["closing_issue_candidates"]:
            issues = ", ".join(f"#{i['number']} {i['url']}".strip() for i in pr["issues"])
            merged = pr.get("merged_at", "")[:10]
            lines.append(f"  PR #{pr['pr']} merged {merged}  {pr['url']}")
            lines.append(f"       closes: {issues}")
    else:
        lines.append("  (없음)")
    lines.append("")

    lines.append(f"■ worktree 정리 후보 ({len(result['worktree_candidates'])})")
    if result["worktree_candidates"]:
        for wt in result["worktree_candidates"]:
            lines.append(f"  {wt['path']} ({wt['branch']})")
            lines.append(f"       후보 명령: git worktree remove {shlex.quote(wt['path'])}")
    else:
        lines.append("  (없음)")
    lines.append("")

    lines.append(f"■ untracked 잔여물 ({len(result['untracked'])})")
    if result["untracked"]:
        for p in result["untracked"]:
            lines.append(f"  {p}")
    else:
        lines.append("  (없음)")
    lines.append("")

    lines.append("■ memory-update 리마인드")
    lines.append("  이번 merge/cleanup 에서 영속할 교훈이 있으면 /feedback-review 또는 /memory-update 로 검토")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="PR merge 후 정리 후보 advisory 리포트")
    ap.add_argument("--project-dir", default=None, help="대상 프로젝트 절대경로(기본: cwd)")
    ap.add_argument("--repo", default=None, help="owner/name (생략 시 gh repo view 로 추론)")
    ap.add_argument("--recent-limit", type=int, default=20, help="최근 merged/closed PR 조회 수")
    ap.add_argument("--no-fetch", action="store_true", help="시작 시 git fetch origin 을 생략")
    ap.add_argument("--json", action="store_true", help="사람용 리포트 대신 JSON 출력")
    args = ap.parse_args(argv)

    project_dir = os.path.abspath(args.project_dir or os.getcwd())
    result = collect(project_dir, repo=args.repo, recent_limit=args.recent_limit, fetch=not args.no_fetch)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(render(result))


if __name__ == "__main__":
    main()
