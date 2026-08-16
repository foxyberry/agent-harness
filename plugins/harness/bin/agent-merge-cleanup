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
        "number,title,url,mergedAt,closedAt,headRefName,headRefOid,isCrossRepository,closingIssuesReferences",
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


def _latest_prs_by_branch(prs):
    latest = {}
    for pr in prs:
        if pr.get("isCrossRepository"):
            continue
        branch = pr.get("headRefName")
        if not branch:
            continue
        timestamp = pr.get("closedAt") or pr.get("mergedAt") or ""
        previous = latest.get(branch)
        previous_timestamp = (
            (previous.get("closedAt") or previous.get("mergedAt") or "")
            if previous else ""
        )
        if previous is None or timestamp > previous_timestamp:
            latest[branch] = pr
    return latest


def _local_branch_candidates(project_dir, prs, base_ref, protected_base):
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

    for branch, pr in _latest_prs_by_branch(prs).items():
        if branch not in existing or branch in candidates:
            continue
        local_tip = _out(
            ["git", "rev-parse", "--verify", f"refs/heads/{branch}"], project_dir
        )
        pr_tip = pr.get("headRefOid") or ""
        tip_matches = bool(local_tip and pr_tip and local_tip == pr_tip)
        state = "merged" if pr.get("mergedAt") else "closed"
        candidates[branch] = {
            "branch": branch,
            "reason": (
                "pr-diverged" if not tip_matches
                else "pr" if state == "merged"
                else "pr-closed"
            ),
            "force": tip_matches and state == "merged",
            "pr": pr.get("number"),
            "state": state,
            "url": pr.get("url") or "",
            "local_tip": local_tip or "",
            "pr_tip": pr_tip,
        }
    return sorted(candidates.values(), key=lambda c: c["branch"])


def _unexplained_branches(project_dir, local_candidates, remote_candidates, protected_base):
    """어느 후보에도 안 걸린 브랜치. **정리 후보가 아니라 "판단 필요"다.**

    후보는 두 경로로만 만들어진다 — main 의 조상이거나, 조회해 온 PR 의 head 와 이름이
    맞거나. 둘 다 아닌 브랜치는 지금까지 리포트에서 **통째로 빠졌다.** 목록에 없는 것과
    존재하지 않는 것이 구별이 안 되니 "정리할 게 없네" 로 읽힌다(이슈 #78).

    두 가지가 여기로 떨어지고, 둘 다 사람이 봐야 한다.

    1. **PR 이 아예 없는 브랜치** — 로컬 전용 리뷰 브랜치 같은 것. GitHub 의
       `refs/pull/N/head` 백업이 없어서 지우면 **되살릴 방법이 없는 유일한 부류**다.
    2. **PR 은 있는데 조회 상한 밖으로 밀린 브랜치** — 오래된 PR 이라 안 가져왔을 뿐이다.
       `--recent-limit` 를 올리면 후보로 내려온다.

    바깥에서는 둘이 똑같이 생겼다. 그래서 **분류하지 않고 둘 다 보여준 뒤**,
    조회가 잘렸으면 상한을 올려 보라고 알린다. 삭제 명령은 어느 쪽에도 제안하지 않는다.
    """
    base = {protected_base, "main", "master", "develop"}
    # 체크아웃 중인 브랜치는 **로컬에서만** 뺀다 — git 이 삭제를 거부하니 후보가 될 수 없다.
    # 원격에는 그 사정이 없다. 여기서 같이 빼면 `origin/<지금 브랜치와 같은 이름>` 이
    # 리포트에서 조용히 사라진다 — 이 함수가 고치려는 것과 똑같은 모양의 버그다.
    local_protected = base | {_current_branch(project_dir)}
    local_known = {c["branch"] for c in local_candidates}
    remote_known = {c["branch"] for c in remote_candidates}
    return {
        "local": sorted(_local_branches(project_dir) - local_protected - local_known),
        "remote": sorted(set(_remote_branches(project_dir)) - base - remote_known),
    }


def _remote_branches(project_dir, remote="origin"):
    raw = _out(
        [
            "git", "for-each-ref",
            "--format", "%(refname:short) %(objectname)",
            f"refs/remotes/{remote}",
        ],
        project_dir,
    )
    if raw is None:
        return {}
    branches = {}
    for line in raw.splitlines():
        ref, _, oid = line.partition(" ")
        if "/" not in ref or ref.endswith("/HEAD"):
            continue
        branches[ref.split("/", 1)[1]] = oid
    return branches


def _recent_prs(project_dir, repo, state, limit):
    data = _out(_pr_list_cmd(repo, state, limit), project_dir, timeout=15)
    if data is None:
        return None
    if not data:
        return []
    try:
        rows = json.loads(data)
        return rows if isinstance(rows, list) else []
    except Exception:
        return None


def _remote_branch_candidates(project_dir, prs):
    existing = _remote_branches(project_dir)
    candidates = []
    for head, pr in _latest_prs_by_branch(prs).items():
        if head not in existing:
            continue
        pr_tip = pr.get("headRefOid") or ""
        tip_matches = bool(pr_tip and existing[head] == pr_tip)
        candidates.append({
            "branch": head,
            "pr": pr.get("number"),
            "state": "merged" if pr.get("mergedAt") else "closed",
            "title": pr.get("title") or "",
            "url": pr.get("url") or "",
            "tip_matches_pr": tip_matches,
        })
    seen = set()
    out = []
    for c in candidates:
        key = (c["branch"], c["pr"])
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out


def _closing_issue_candidates(prs):
    rows = []
    for pr in prs:
        if not pr.get("mergedAt"):
            continue
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


def _safe_worktree_branches(local_candidates):
    return [
        candidate["branch"]
        for candidate in local_candidates
        if candidate.get("reason") == "ancestor"
        or (candidate.get("force") and candidate.get("state") == "merged")
    ]


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
    # 조회는 최근 N건까지만 본다. 그보다 오래된 PR 의 브랜치는 후보에 아예 안 들어가는데,
    # 리포트는 개수만 내니 완전한 목록처럼 읽힌다. 잘렸다는 걸 **알려줘야** 한다.
    #
    # "N건 받아왔으면 잘린 것"으로 보면 오탐이 난다 — 저장소에 딱 N건뿐인 경우도 그렇게
    # 보인다(실제로 이 저장소에서 그랬다). 그래서 **한 건 더 요청해서** 그게 오는지로
    # 판정한다. 오면 확실히 더 있는 것이고, 안 오면 확실히 다 본 것이다. 여분 1건은
    # 판정에만 쓰고 후보 계산에서는 버린다 — `--recent-limit` 의 뜻을 바꾸지 않는다.
    merged_prs_result = _recent_prs(root, resolved_repo, "merged", recent_limit + 1)
    closed_prs_result = _recent_prs(root, resolved_repo, "closed", recent_limit + 1)
    pr_query_ok = merged_prs_result is not None and closed_prs_result is not None
    merged_all = merged_prs_result or []
    closed_all = closed_prs_result or []
    pr_query_truncated = pr_query_ok and (
        len(merged_all) > recent_limit or len(closed_all) > recent_limit
    )
    merged_prs = merged_all[:recent_limit]
    closed_prs = closed_all[:recent_limit]
    prs = merged_prs + closed_prs
    local_candidates = _local_branch_candidates(
        root, prs, cleanup_base_ref, default
    )
    ancestry_local = [
        candidate["branch"]
        for candidate in local_candidates
        if candidate.get("reason") == "ancestor"
    ]
    remote = _remote_branch_candidates(root, prs)
    unexplained = _unexplained_branches(root, local_candidates, remote, default)
    issues = _closing_issue_candidates(merged_prs)
    wts = _worktrees(root, _safe_worktree_branches(local_candidates))
    untracked = _untracked(root)
    return {
        "project_dir": root,
        "repo": resolved_repo,
        "local_repo": cwd_repo,
        "repo_mismatch": bool(repo and cwd_repo and repo != cwd_repo),
        "fetch": fetch_result,
        "pr_query_ok": pr_query_ok,
        "default_branch": default,
        "cleanup_base_ref": cleanup_base_ref,
        "sync": sync,
        "local_merged_branches": ancestry_local,
        "local_branch_candidates": local_candidates,
        "unexplained_branches": unexplained,
        "pr_query_limit": recent_limit,
        "pr_query_truncated": pr_query_truncated,
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
    if result.get("pr_query_ok") is False:
        lines.append("⚠ GitHub PR 조회 실패 — PR 기준 로컬·원격 후보를 못 찾았을 수 있음")
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
    candidates = result.get("local_branch_candidates") or [
        {"branch": b, "force": False} for b in result["local_merged_branches"]
    ]
    lines.append(
        f"■ 로컬 정리 브랜치 삭제 후보 ({len(candidates)}) "
        f"— 기준 {cleanup_base}"
    )
    if candidates:
        for candidate in candidates:
            branch = candidate["branch"]
            if candidate.get("force"):
                lines.append(
                    f"  {branch}  ← PR #{candidate.get('pr')} {candidate.get('state')}  "
                    f"{candidate.get('url') or ''}".rstrip()
                )
                lines.append(
                    f"       후보 명령: git branch -D {shlex.quote(branch)} "
                    "(squash merge는 git ancestry에 없어 -d가 거부할 수 있음)"
                )
            elif candidate.get("reason") == "pr-closed":
                lines.append(
                    f"  {branch}  ← PR #{candidate.get('pr')} closed  "
                    f"{candidate.get('url') or ''}".rstrip()
                )
                lines.append(
                    f"       후보 명령: git branch -d {shlex.quote(branch)} "
                    "(미머지 커밋이 있으면 git이 삭제를 거부함 — 강제 삭제 제안 안 함)"
                )
            elif candidate.get("reason") == "pr-diverged":
                lines.append(
                    f"  {branch}  ← PR #{candidate.get('pr')} {candidate.get('state')} 이후 "
                    "로컬 tip 변경됨"
                )
                lines.append(
                    f"       강제 삭제 제안 안 함 — 확인: git log --oneline "
                    f"{shlex.quote('origin/' + default)}..{shlex.quote(branch)}"
                )
            else:
                lines.append(f"  {branch}  → 후보 명령: git branch -d {shlex.quote(branch)}")
    else:
        lines.append("  (없음)")
    lines.append("")

    unexplained = result.get("unexplained_branches") or {}
    stray_local = unexplained.get("local") or []
    stray_remote = unexplained.get("remote") or []
    if stray_local or stray_remote:
        total = len(stray_local) + len(stray_remote)
        lines.append(f"■ 판단 필요 — 어느 후보에도 안 걸린 브랜치 ({total})")
        lines.append("  자동으로 못 정한다. 삭제 명령은 일부러 제안하지 않는다.")
        for branch in stray_local:
            lines.append(f"  (로컬)  {branch}")
            lines.append(
                f"       확인: git log --oneline {shlex.quote('origin/' + default)}"
                f"..{shlex.quote(branch)}"
            )
        for branch in stray_remote:
            lines.append(f"  (원격)  origin/{branch}")
            lines.append(
                f"       확인: git log --oneline {shlex.quote('origin/' + default)}"
                f"..{shlex.quote('origin/' + branch)}"
            )
        if result.get("pr_query_truncated"):
            limit = result.get("pr_query_limit")
            lines.append("")
            lines.append(
                f"  ⚠ PR 조회가 최근 {limit}건에서 잘렸다 — 위 브랜치 중 일부는 그냥"
            )
            lines.append(
                f"    오래된 PR 이라 안 가져온 것일 수 있다. 확인: --recent-limit "
                f"{int(limit) * 5} 로 다시 실행"
            )
        else:
            lines.append("")
            lines.append(
                "  PR 은 전부 조회했다. 즉 이 브랜치들에는 PR 기록이 없다 —"
            )
            lines.append(
                "  GitHub 의 refs/pull/N/head 백업도 없어서 지우면 되살릴 방법이 없다."
            )
        lines.append("")

    lines.append(f"■ 원격 브랜치 삭제 후보 ({len(result['remote_branch_candidates'])})")
    if result["remote_branch_candidates"]:
        for c in result["remote_branch_candidates"]:
            lines.append(
                f"  origin/{c['branch']}  ← PR #{c['pr']} {c['state']}  {c['url']}"
            )
            if c.get("tip_matches_pr") is False:
                lines.append("       삭제 제안 안 함 — 원격 tip 이 PR head 이후 변경됨")
            elif c.get("state") == "closed":
                lines.append(
                    "       삭제 제안 안 함 — PR이 머지되지 않아 원격이 유일한 사본일 수 있음"
                )
            else:
                lines.append(
                    f"       후보 명령: git push origin --delete {shlex.quote(c['branch'])}"
                )
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
