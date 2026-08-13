#!/usr/bin/env python3
"""
작업 핸드오프 (portable work handoff).

세션·툴·머신·사람을 넘어 작업을 이어받기 위한 "이식 가능한 핸드오프 상태"를
git 에 커밋되는 파일로 관리한다.

왜 필요한가:
  - transcript(.jsonl) 는 로컬·툴 종속이다. Claude=`~/.claude/projects/...`,
    Codex=`~/.codex/sessions/...` 로 위치·포맷이 다르고, 둘 다 repo 밖이라
    다른 머신/사람/툴은 읽을 수 없다. (참고: cross-machine-feedback-placement)
  - 반면 이 핸드오프 파일은 `.claude/handoff/<branch>.md` 에 커밋되므로
    clone/pull 하는 모든 머신·사람·에이전트가 동일하게 본다.

계층:
  - 이식 경로(1순위) = 이 커밋된 핸드오프 파일  → 누구나/어디서나/어느 툴이나
  - 깊은 복구(보강)  = 로컬 transcript(.jsonl)  → 같은 머신·같은 툴일 때만

서브커맨드:
  save  현재 git 사실을 자동 수집해 핸드오프 파일을 생성/갱신한다.
        서술(요약/완료/다음/검증)은 에이전트가 인자로 채운다.
  load  현재 브랜치 핸드오프 파일 + 현재 git 사실을 출력한다(이식 경로).
        로컬 transcript 가 있으면 "깊은 복구 가능" 힌트를 덧붙인다.

툴 무관: Claude(.claude/skills) · Codex(.agents/skills) 모두 이 스크립트를 호출한다.
stdlib 전용 (외부 의존성 없음). Python 3.8+.

사용:
  python3 scripts/handoff/handoff.py save \
      --agent claude --summary "..." --done "..." --next "..." --verify "..."
  python3 scripts/handoff/handoff.py load
"""
import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from datetime import datetime, timedelta, timezone

HANDOFF_DIR = ".claude/handoff"
AUTO_MARK = "<!-- handoff:auto -->"
SNIP = 500


def run(cmd, cwd=None):
    """셸 명령 실행 후 (stdout, ok) 반환. 실패해도 예외 없이 빈 문자열."""
    try:
        out = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=20
        )
        return out.stdout.strip(), out.returncode == 0
    except Exception:
        return "", False


def repo_root(explicit=None):
    """핸드오프를 저장/조회할 프로젝트 루트. 우선순위:
    1) 명시 인자(--project-dir) — cwd 무관하게 확정. Codex 처럼 스크립트를 스킬 폴더에서
       실행할 때, 사용자 프로젝트를 명시하기 위한 것(스킬 폴더는 플러그인 캐시라 repo 밖일 수 있음).
    2) CLAUDE_PROJECT_DIR env — Claude 훅/플러그인이 세팅.
    3) git toplevel(cwd 기준) — cwd 가 사용자 프로젝트 안일 때.
    4) cwd 폴백.
    명시/env 경로가 git repo(또는 그 하위)면 toplevel 로 정규화한다."""
    cand = explicit or os.environ.get("CLAUDE_PROJECT_DIR")
    if cand:
        cand = os.path.abspath(os.path.expanduser(cand))
        out, ok = run(["git", "rev-parse", "--show-toplevel"], cwd=cand)
        return out if ok and out else cand
    out, ok = run(["git", "rev-parse", "--show-toplevel"])
    return out if ok and out else os.getcwd()


def current_branch(root):
    out, ok = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=root)
    return out if ok and out else "DETACHED"


def safe_name(branch):
    """브랜치명을 파일명으로 — '/' 등 경로문자를 '-' 로 치환."""
    return branch.replace("/", "-").replace(" ", "_")


def handoff_path(root, branch):
    return os.path.join(root, HANDOFF_DIR, safe_name(branch) + ".md")


def now_iso():
    # 로컬 타임존 포함 ISO (예: 2026-06-30T14:05:00+09:00)
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def machine_name():
    """Return an explicit machine label without leaking the host name by default."""
    return os.environ.get("HARNESS_HANDOFF_MACHINE", "비공개")


def git_facts(root):
    """이어받는 쪽이 transcript 없이도 현재 상태를 대조할 수 있게 git 사실 수집."""
    branch = current_branch(root)
    status, _ = run(["git", "status", "-sb"], cwd=root)
    stat_unstaged, _ = run(["git", "diff", "--stat"], cwd=root)
    stat_staged, _ = run(["git", "diff", "--cached", "--stat"], cwd=root)
    # origin/main 대비 앞선 커밋 (base 가 main 이 아닐 수 있으나 가장 흔한 기준)
    ahead, ahead_ok = run(
        ["git", "log", "--oneline", "origin/main..HEAD"], cwd=root
    )
    # 열린 PR (gh 있고 네트워크 되면). 실패해도 무시.
    pr, pr_ok = run(
        ["gh", "pr", "list", "--head", branch,
         "--json", "number,title,url",
         "--jq", '.[] | "#\\(.number) \\(.title) — \\(.url)"'],
        cwd=root,
    )
    return {
        "branch": branch,
        "status": status,
        "stat_unstaged": stat_unstaged,
        "stat_staged": stat_staged,
        "ahead": ahead if ahead_ok else "(origin/main 대비 비교 불가 — fetch 필요)",
        "pr": pr if (pr_ok and pr) else "(없음 또는 조회 불가)",
    }


def transcript_hint(root):
    """같은 머신에 **이 프로젝트의** 로컬 transcript 가 있으면 '깊은 복구 가능' 힌트 반환.

    ⚠️ 양쪽 다 반드시 프로젝트로 스코프한다. 예전 Codex 분기는 `~/.codex/sessions` 전체를
    훑어 "존재함"만 알렸는데, 그 문구는 어떤 세션이 이 프로젝트 것인지 말해주지 않아
    사람·모델이 직접 로그를 뒤지게 만들었고, 손 탐색에는 스코핑이 없어서 **전역 mtime 최신인
    남의 프로젝트 세션**을 직전 작업으로 오인했다(이슈 #95). 힌트는 개수를 세는 게 목적이
    아니라 **다음에 칠 명령**을 알려주는 것이다 — 없으면 없다고 분명히 말한다.
    """
    hints = []
    # Claude: ~/.claude/projects/<cwd '/'→'-'>/*.jsonl — 디렉터리 자체가 프로젝트별로
    # 갈리므로 한 번의 listdir 로 스코프와 개수가 동시에 나온다(싸다).
    claude_dir = _claude_project_dir(root)
    if os.path.isdir(claude_dir):
        jsonls = [f for f in os.listdir(claude_dir) if f.endswith(".jsonl")]
        if jsonls:
            hints.append(
                f"Claude transcript {len(jsonls)}개 @ {claude_dir} "
                f"→ `/fw --from claude` 또는 `/fw-both` 로 깊은 복구 가능 (이 머신 한정)"
            )
    # Codex: 프로젝트 구분이 파일 안(session_meta.cwd)에 있어 개수를 세려면 전부 열어야 한다.
    # 힌트에 필요한 건 개수가 아니라 **다음에 칠 명령**이므로 존재 여부만 확인하고 멈춘다.
    if _has_project_codex_rollout(root):
        hints.append(
            f"Codex rollout 있음 @ {_codex_sessions_dir()} "
            f"→ `/fw --from codex` 또는 `/fw-both` 로 깊은 복구 가능 (이 머신 한정)"
        )
    return hints


def _claude_project_dir(root):
    """Claude Code project transcript dir for this repo, if present."""
    proj_key = _claude_project_key(root)
    return os.path.join(os.path.expanduser("~"), ".claude", "projects", proj_key)


def _claude_project_key(path):
    """Claude Code project dir key. Current Claude Code replaces path separators and dots."""
    return path.replace("/", "-").replace(".", "-")


def _recent_claude_transcripts(root, limit=2, exclude_stem=None):
    """최근 Claude Code top-level transcript 목록. subagents 는 보조 로그라 기본 제외.
    exclude_stem: 파일명 stem(=세션 UUID)이 이것과 같으면 제외 — fw both 에서 현재
    실행 중인 Claude 세션(지금 fw 를 부른 그 세션)을 직전 작업으로 오인하지 않도록."""
    claude_dir = _claude_project_dir(root)
    if not os.path.isdir(claude_dir):
        return []
    rows = []
    try:
        for fn in os.listdir(claude_dir):
            if not fn.endswith(".jsonl"):
                continue
            if exclude_stem and os.path.splitext(fn)[0] == exclude_stem:
                continue
            fp = os.path.join(claude_dir, fn)
            try:
                rows.append((os.path.getmtime(fp), os.path.getsize(fp), fp))
            except OSError:
                continue
    except OSError:
        return []
    rows.sort(reverse=True)
    return rows[:limit]


def _clip(text, n=SNIP):
    text = re.sub(r"\s+", " ", (text or "").strip())
    return text if len(text) <= n else text[: n - 1] + "…"


def _content_text(content):
    """Claude message content(str|list) 에서 사람이 읽을 텍스트만 추출."""
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        return _content_text(content.get("content") or content.get("text") or "")
    if not isinstance(content, list):
        return ""
    parts = []
    for block in content:
        if not isinstance(block, dict):
            if isinstance(block, str):
                parts.append(block)
            continue
        if block.get("type") == "text":
            parts.append(block.get("text", ""))
        elif block.get("type") == "tool_result":
            parts.append(_content_text(block.get("content", "")))
    return "\n".join(str(p) for p in parts if p)


def _task_notes(text):
    notes = []
    for m in re.finditer(r"<task-notification>(.*?)</task-notification>", text or "", re.S):
        body = m.group(1)
        note = {}
        for key in ("task-id", "status", "summary", "output-file"):
            km = re.search(rf"<{key}>(.*?)</{key}>", body, re.S)
            if km:
                note[key] = km.group(1).strip()
        if note:
            notes.append(note)
    return notes


def _summarize_claude_transcript(path):
    """Claude Code JSONL 에서 이어받기에 필요한 마지막 신호만 요약한다."""
    summary = {
        "last_prompt": "",
        "last_users": [],
        "last_assistants": [],
        "last_tools": [],
        "task_notes": [],
        "pr_links": [],
        "rate_limit": "",
    }
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    data = json.loads(line)
                except Exception:
                    continue

                typ = data.get("type")
                if typ == "last-prompt" and data.get("lastPrompt"):
                    summary["last_prompt"] = data.get("lastPrompt", "")

                if typ == "pr-link":
                    summary["pr_links"].append(
                        f"#{data.get('prNumber')} {data.get('prUrl')}"
                    )

                content = data.get("content")
                if isinstance(content, str):
                    for note in _task_notes(content):
                        summary["task_notes"].append(note)

                msg = data.get("message")
                if not isinstance(msg, dict):
                    continue
                role = msg.get("role")
                blocks = msg.get("content")

                if role == "user":
                    text = _content_text(blocks)
                    if "<local-command-caveat>" in text:
                        continue
                    for note in _task_notes(text):
                        summary["task_notes"].append(note)
                    if text and "<task-notification>" not in text:
                        summary["last_users"].append(_clip(text))
                        summary["last_users"] = summary["last_users"][-3:]

                elif role == "assistant":
                    if isinstance(blocks, list):
                        for block in blocks:
                            if not isinstance(block, dict):
                                continue
                            if block.get("type") == "text":
                                txt = _clip(block.get("text", ""))
                                if txt:
                                    summary["last_assistants"].append(txt)
                                    summary["last_assistants"] = summary["last_assistants"][-3:]
                            elif block.get("type") == "tool_use":
                                name = block.get("name", "")
                                inp = block.get("input", {}) or {}
                                cmd = inp.get("command") or inp.get("file_path") or ""
                                summary["last_tools"].append(_clip(f"{name}: {cmd}", 240))
                                summary["last_tools"] = summary["last_tools"][-5:]

                local = data.get("content") if data.get("subtype") == "local_command" else ""
                if isinstance(local, str) and "session limit" in local:
                    summary["rate_limit"] = _clip(local)
    except OSError:
        pass
    return summary


def _format_claude_deep_recovery(root, limit=2, transcript=None, exclude_stem=None):
    paths = []
    if transcript:
        paths = [(0, 0, os.path.expanduser(transcript))]
    else:
        paths = _recent_claude_transcripts(root, limit=limit, exclude_stem=exclude_stem)
    if not paths:
        return []

    out = ["## 🧩 Claude JSONL 빠른 복구 (이 머신 한정)"]
    for mt, size, path in paths:
        if not os.path.exists(path):
            out.append(f"- 없음: `{path}`")
            continue
        label = os.path.basename(path)
        when = datetime.fromtimestamp(os.path.getmtime(path)).astimezone().isoformat(timespec="seconds")
        out.append(f"### `{label}`")
        out.append(f"- 경로: `{path}`")
        out.append(f"- 갱신: {when} · 크기: {os.path.getsize(path)} bytes")
        s = _summarize_claude_transcript(path)
        if s["last_prompt"]:
            out.append(f"- 마지막 프롬프트: {_clip(s['last_prompt'], 300)}")
        if s["last_users"]:
            out.append("- 최근 사용자 입력:")
            for item in s["last_users"]:
                out.append(f"  - {item}")
        if s["last_assistants"]:
            out.append("- 최근 assistant 응답:")
            for item in s["last_assistants"]:
                out.append(f"  - {item}")
        if s["last_tools"]:
            out.append("- 최근 도구 호출:")
            for item in s["last_tools"]:
                out.append(f"  - `{item}`")
        if s["task_notes"]:
            out.append("- 백그라운드 task 알림:")
            task_notes = []
            seen_tasks = set()
            for note in s["task_notes"]:
                key = (note.get("task-id"), note.get("output-file"), note.get("summary"))
                if key in seen_tasks:
                    continue
                seen_tasks.add(key)
                task_notes.append(note)
            for note in task_notes[-5:]:
                summary = note.get("summary", "(summary 없음)")
                status = note.get("status", "?")
                task_id = note.get("task-id", "?")
                out.append(f"  - {task_id} [{status}] {summary}")
                if note.get("output-file"):
                    out.append(f"    output: `{note['output-file']}`")
        if s["pr_links"]:
            out.append("- PR 링크:")
            for link in list(dict.fromkeys(s["pr_links"]))[-3:]:
                out.append(f"  - {link}")
        if s["rate_limit"]:
            out.append(f"- 세션 제한 신호: {s['rate_limit']}")
    return out


# ---------- Codex rollout 탐지·요약 (fw 용) ----------

def _codex_sessions_dir():
    return os.path.join(os.path.expanduser("~"), ".codex", "sessions")


def _codex_rollout_meta(path):
    """rollout 첫 줄 session_meta → (session_id, cwd). 아니면 (None, None)."""
    try:
        with open(path, encoding="utf-8") as f:
            d = json.loads(f.readline())
        if d.get("type") == "session_meta":
            p = d.get("payload") or {}
            return p.get("id"), p.get("cwd")
    except Exception:
        pass
    return None, None


def _project_matcher(root):
    """`cwd` → 이 프로젝트 소속인가 를 판정하는 콜러블.

    repo_identity 는 build.sh 가 이 스크립트와 같은 디렉토리에 co-locate 한다. 없으면
    (스크립트만 단독 복사된 경우) 예전 경로 prefix 판정으로 떨어진다 — worktree 를 놓치지만
    죽지는 않는다."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from repo_identity import ProjectMatcher
    except ImportError:
        return lambda cwd: cwd == root or bool(cwd and cwd.startswith(root + os.sep))
    m = ProjectMatcher(root)
    # 지금 살아있는 worktree 를 관측 기록한다. 자동 회고(HARNESS_AUTO_REFLECT)는 **기본 꺼짐**
    # 이라 그쪽에만 기록을 맡기면 캐시가 영영 안 생긴다 — 그러면 worktree 를 지운 뒤 fw/history
    # 가 그 세션을 못 찾는다. 회고를 안 켠 사용자도 되짚기가 되도록 여기서도 남긴다.
    m.record_worktrees()
    return m.belongs


def _recent_codex_rollouts(root, limit=2, days=30, exclude_sid=None):
    """이 프로젝트(session_meta.cwd == root 또는 그 하위) 의 최근 Codex rollout
    [(mtime, size, path)]. 시작 날짜 디렉터리와 무관하게 전체 트리에서 mtime이 최근
    `days` 안인 파일만 metadata를 읽는다(resume된 오래된 세션 누락 방지).
    exclude_sid: session_meta.id 가 이것과 같으면 제외 — fw both 에서 현재 실행 중인
    Codex 세션(지금 fw 를 부른 그 세션)을 직전 작업으로 오인하지 않도록."""
    base = _codex_sessions_dir()
    if not os.path.isdir(base):
        return []
    today = datetime.now()
    cutoff = today.timestamp() - (days * 86400)
    matcher = _project_matcher(root)
    rows = []
    for directory, _dirs, names in os.walk(base):
        for fn in names:
            if not (fn.startswith("rollout-") and fn.endswith(".jsonl")):
                continue
            fp = os.path.join(directory, fn)
            try:
                mtime = os.path.getmtime(fp)
                size = os.path.getsize(fp)
            except OSError:
                continue
            if mtime < cutoff:
                continue
            sid, cwd = _codex_rollout_meta(fp)
            # 경로 prefix 가 아니라 git 저장소 identity 로 판정 — worktree 가 프로젝트
            # 폴더 밖에 있어도(`~/.codex/worktrees/`, 형제 `.agent-worktrees/`) 잡힌다.
            if not matcher(cwd):
                continue
            if exclude_sid and sid == exclude_sid:
                continue
            rows.append((mtime, size, fp))
    rows.sort(reverse=True)
    return rows[:limit]


def _has_project_codex_rollout(root, days=30):
    """이 프로젝트의 Codex rollout 이 하나라도 있나 — 찾는 즉시 멈춘다.

    `_recent_codex_rollouts` 를 불러 개수를 세면 rollout 전부의 metadata 를 열고 cwd 마다
    git identity 를 물어야 한다(이 머신 기준 1200개 이상 = 수백 ms). 그 비용은 `--deep` 요약에는
    값지지만, 힌트 한 줄 때문에 **평범한 `load` 마다** 물릴 이유가 없다.

    그래서 (1) 최신 파일부터 보고 (2) 첫 매칭에서 끝낸다 — 있는 경우엔 대개 몇 개만 읽는다.
    없는 경우에만 전부 확인하는데, 그 확인은 건너뛰지 않는다: 성급히 '있음' 이라고 하면
    사용자를 손 탐색으로 보내고, 손 탐색에는 프로젝트 스코핑이 없다(이슈 #95).
    """
    base = _codex_sessions_dir()
    if not os.path.isdir(base):
        return False
    cutoff = datetime.now().timestamp() - (days * 86400)
    cands = []
    for directory, _dirs, names in os.walk(base):
        for fn in names:
            if not (fn.startswith("rollout-") and fn.endswith(".jsonl")):
                continue
            fp = os.path.join(directory, fn)
            try:
                mtime = os.path.getmtime(fp)
            except OSError:
                continue
            if mtime >= cutoff:
                cands.append((mtime, fp))
    if not cands:
        return False
    cands.sort(reverse=True)  # 최신부터 — 내 프로젝트 세션이 있으면 대개 앞쪽에 있다
    matcher = _project_matcher(root)
    for _mtime, fp in cands:
        if matcher(_codex_rollout_meta(fp)[1]):
            return True
    return False


def _summarize_codex_rollout(path):
    """Codex rollout JSONL 에서 이어받기 신호(최근 user/assistant 텍스트, 도구명)만 요약."""
    summary = {"last_users": [], "last_assistants": [], "last_tools": []}
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                if d.get("type") != "response_item":
                    continue
                p = d.get("payload") or {}
                pt = p.get("type")
                if pt == "message":
                    role = p.get("role")
                    texts = [
                        b.get("text", "")
                        for b in (p.get("content") or [])
                        if isinstance(b, dict)
                        and b.get("type") in ("input_text", "output_text", "text")
                        and (b.get("text") or "").strip()
                    ]
                    if not texts:
                        continue
                    joined = _clip("\n".join(texts))
                    if role == "user":
                        summary["last_users"].append(joined)
                        summary["last_users"] = summary["last_users"][-3:]
                    elif role == "assistant":
                        summary["last_assistants"].append(joined)
                        summary["last_assistants"] = summary["last_assistants"][-3:]
                elif pt == "function_call":
                    name = p.get("name", "")
                    if name:
                        summary["last_tools"].append(_clip(name, 120))
                        summary["last_tools"] = summary["last_tools"][-5:]
    except OSError:
        pass
    return summary


def _format_codex_deep_recovery(root, limit=1, session=None, exclude_sid=None):
    if session:
        paths = [(0, 0, os.path.expanduser(session))]
    else:
        paths = _recent_codex_rollouts(root, limit=limit, exclude_sid=exclude_sid)
    if not paths:
        return ["## 🧩 Codex rollout: 이 프로젝트의 최근 세션 로그 없음 (이 머신 한정)"]
    out = ["## 🧩 Codex rollout 빠른 복구 (이 머신 한정)"]
    for _mt, _size, path in paths:
        if not os.path.exists(path):
            out.append(f"- 없음: `{path}`")
            continue
        when = datetime.fromtimestamp(os.path.getmtime(path)).astimezone().isoformat(timespec="seconds")
        out.append(f"### `{os.path.basename(path)}`")
        out.append(f"- 경로: `{path}`")
        out.append(f"- 갱신: {when} · 크기: {os.path.getsize(path)} bytes")
        s = _summarize_codex_rollout(path)
        if s["last_users"]:
            out.append("- 최근 사용자 입력:")
            for item in s["last_users"]:
                out.append(f"  - {item}")
        if s["last_assistants"]:
            out.append("- 최근 assistant 응답:")
            for item in s["last_assistants"]:
                out.append(f"  - {item}")
        if s["last_tools"]:
            out.append("- 최근 도구 호출:")
            for item in s["last_tools"]:
                out.append(f"  - `{item}`")
    return out


def _parse_since(value):
    match = re.fullmatch(r"(\d+)([mhdw])", value or "")
    if not match:
        raise ValueError("--since 형식: 30m, 12h, 7d, 2w")
    amount = int(match.group(1))
    if amount <= 0:
        raise ValueError("--since는 1 이상이어야 합니다")
    units = {"m": 60, "h": 3600, "d": 86400, "w": 604800}
    seconds = amount * units[match.group(2)]
    if seconds > 3650 * 86400:
        raise ValueError("--since는 최대 10년까지 허용합니다")
    return seconds


def _contains_keyword(path, keyword):
    if not keyword:
        return True
    needle = keyword.casefold()
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return any(needle in line.casefold() for line in handle)
    except OSError:
        return False


def _history_rows(root, from_tool="both", limit=20, since="30d", grep=None, no_content=False):
    cutoff = datetime.now().timestamp() - _parse_since(since)
    candidates = []
    if from_tool in ("claude", "both"):
        for mtime, size, path in _recent_claude_transcripts(root, limit=10000):
            if mtime >= cutoff:
                candidates.append(("claude", mtime, size, path))
    if from_tool in ("codex", "both"):
        days = max(1, int(_parse_since(since) / 86400) + 1)
        for mtime, size, path in _recent_codex_rollouts(root, limit=10000, days=days):
            if mtime >= cutoff:
                candidates.append(("codex", mtime, size, path))
    candidates.sort(key=lambda item: item[1], reverse=True)
    if grep:
        candidates = candidates[:200]

    rows = []
    for tool, mtime, size, path in candidates:
        if grep and not _contains_keyword(path, grep):
            continue
        if no_content:
            snippet = ""
            if tool == "claude":
                project_match = "Claude project directory key"
            else:
                _sid, cwd = _codex_rollout_meta(path)
                project_match = "exact cwd" if cwd == root else "nested cwd"
        elif tool == "claude":
            summary = _summarize_claude_transcript(path)
            snippet = summary["last_prompt"]
            project_match = "Claude project directory key"
        else:
            _sid, cwd = _codex_rollout_meta(path)
            summary = _summarize_codex_rollout(path)
            snippet = summary["last_users"][-1] if summary["last_users"] else ""
            project_match = "exact cwd" if cwd == root else "nested cwd"
        if "\ufffd" in snippet:
            snippet = ""
        rows.append({
            "time": datetime.fromtimestamp(mtime).astimezone().isoformat(timespec="seconds"),
            "tool": tool,
            "path": path,
            "size": size,
            "project_match": project_match,
            "snippet": _clip(snippet, 160),
            "resume_command": _history_resume_command(root, path),
        })
        if len(rows) >= limit:
            break
    return rows


def _history_resume_command(root, path):
    return " ".join([
        shlex.quote(sys.executable),
        shlex.quote(os.path.abspath(__file__)),
        "fw",
        "--session",
        shlex.quote(path),
        "--project-dir",
        shlex.quote(root),
    ])


def _render_history(root, rows, no_content=False):
    if not rows:
        # "없음" 일 때야말로 어느 프로젝트를 봤는지 밝혀야 한다 — 대상을 잘못 지목한 것과
        # 정말 로그가 없는 것이 여기서는 똑같이 보인다.
        return (
            "# Session history\n\n"
            f"- Project: `{root}`\n\n"
            "조건에 맞는 Claude/Codex 세션 로그가 없습니다."
        )
    lines = [
        "# Session history (read-only)",
        "",
        f"- Project: `{root}`",
        f"- Results: {len(rows)}",
    ]
    for index, row in enumerate(rows, 1):
        lines.extend([
            "",
            f"## {index}. {row['time']} · {row['tool']}",
            f"- 로그 경로: `{row['path']}`",
            f"- 프로젝트 매치: {row['project_match']} · {row['size']} bytes",
        ])
        if not no_content:
            lines.append(f"- 마지막 사용자 입력: {row['snippet'] or '(파싱 가능한 입력 없음)'}")
        lines.append(f"- 이어받기: `{row['resume_command']}`")
    return "\n".join(lines)


def cmd_history(args):
    root = repo_root(getattr(args, "project_dir", None))
    if args.limit <= 0:
        print("ERROR: --limit은 1 이상이어야 합니다.", file=sys.stderr)
        return 2
    try:
        rows = _history_rows(
            root,
            from_tool=args.from_tool,
            limit=args.limit,
            since=args.since,
            grep=args.grep,
            no_content=args.no_content,
        )
    except ValueError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps({"project": root, "rows": rows}, ensure_ascii=False, indent=2))
    else:
        print(_render_history(root, rows, no_content=args.no_content))
    return 0


def _target_lines(root, explicit):
    """이 실행이 **어느 프로젝트를 봤는지**, 그리고 **왜 거기로 정했는지** 를 맨 앞에 밝힌다.

    이어받기는 대상을 잘못 지목해도 출력이 멀쩡해 보인다 — 그 저장소의 브랜치와 세션이
    정상적으로 나오기 때문이다. 툴은 시킨 대로 한 것이라 그 자체는 결함이 아니지만,
    **틀렸다는 걸 알아챌 방법이 없는 것**은 결함이다. 읽는 사람이 의도한 프로젝트와
    대조할 수 있게 한 줄 남긴다(이슈 #95 의 "감지한 cwd/git root, 선택 이유를 표시").
    """
    if explicit:
        why = "`--project-dir` 인자"
    elif os.environ.get("CLAUDE_PROJECT_DIR"):
        why = "`CLAUDE_PROJECT_DIR` 환경변수"
    else:
        why = "현재 디렉터리"
    return [f"- 대상 프로젝트: `{root}` (지목: {why})", ""]


def _facts_lines(facts, header):
    """git_facts dict 를 사람이 읽는 마크다운 줄로 (load·fw 공용)."""
    return [
        header,
        f"- 브랜치: `{facts['branch']}`",
        "- origin/main 대비 커밋:", "```", facts["ahead"] or "(없음)", "```",
        "- 변경 파일 (status -sb):", "```", facts["status"] or "(없음)", "```",
        f"- 열린 PR: {facts['pr']}",
    ]


def _review_ledger_summary(root, branch):
    """현재 브랜치의 로컬 review ledger를 커밋 handoff용 Markdown으로 축약."""
    directory = os.path.join(root, ".claude", ".cache", "review-ledger")
    try:
        names = sorted(os.listdir(directory))
    except OSError:
        return ""
    candidates = []
    other_branches = []
    for name in names:
        if not re.fullmatch(r"pr-\d+\.json", name):
            continue
        try:
            path = os.path.join(directory, name)
            with open(path, encoding="utf-8") as handle:
                ledger = json.load(handle)
        except (OSError, ValueError):
            continue
        try:
            mtime_ns = os.stat(path).st_mtime_ns
        except OSError:
            continue
        candidate = (mtime_ns, name, ledger)
        if ledger.get("branch") == branch:
            candidates.append(candidate)
        else:
            other_branches.append(candidate)
    branch_warning = ""
    if not candidates and len(other_branches) == 1:
        candidates = other_branches
        old_branch = candidates[0][2].get("branch") or "(unknown)"
        branch_warning = (
            f"- ⚠️ 원장 브랜치 `{old_branch}`와 현재 `{branch}`가 다름 — "
            "브랜치 rename 여부 확인"
        )
    elif not candidates and other_branches:
        branches = sorted({
            item[2].get("branch") or "(unknown)" for item in other_branches
        })
        return (
            "## 리뷰 원장 경고\n"
            f"- 현재 브랜치 `{branch}`와 일치하는 원장은 없고 다른 브랜치 원장이 "
            f"{len(other_branches)}개 있음: {', '.join(f'`{item}`' for item in branches)}"
        )
    if candidates:
        latest_mtime = max(item[0] for item in candidates)
        latest = [item for item in candidates if item[0] == latest_mtime]
        _mtime, name, ledger = latest[0]
        findings = [
            item for item in ledger.get("findings", [])
            if isinstance(item, dict) and item.get("status") == "open"
        ]
        lines = [
            f"## 리뷰 원장 — PR #{ledger.get('pr', '?')}",
            f"- 로컬 원장: `.claude/.cache/review-ledger/{name}` (gitignore, 원본은 이 머신 한정)",
            f"- 원장 상태: round {ledger.get('round', '?')} · updated `{ledger.get('updated_at', '?')}`",
        ]
        if branch_warning:
            lines.append(branch_warning)
        if len(latest) > 1:
            lines.append(
                "- ⚠️ 최신 원장 시각이 같은 후보가 여러 개임: "
                + ", ".join(f"`{item[1]}`" for item in latest)
            )
        reviewers = ledger.get("reviewers", [])
        for reviewer in reviewers:
            if not isinstance(reviewer, dict):
                continue
            suffix = f" · thread `{reviewer['thread']}`" if reviewer.get("thread") else ""
            lines.append(f"- reviewer: {reviewer.get('name', '?')}{suffix}")
        if findings:
            lines.append("- open findings (신규 탐색 전에 먼저 재검수):")
            for item in findings:
                loc = item.get("file") or "-"
                if item.get("line"):
                    loc += f":{item['line']}"
                reviewer = item.get("reviewer")
                thread = item.get("thread")
                source = ""
                if reviewer or thread:
                    source = " · " + (reviewer or "reviewer")
                    if thread:
                        source += f" thread `{thread}`"
                lines.append(
                    f"  - {item.get('id', '?')} [{item.get('severity', '?')}] "
                    f"{loc} — {item.get('claim', '')}{source} "
                    f"(opened round {item.get('round_opened', '?')})"
                )
        else:
            lines.append("- open findings: 없음")
        return "\n".join(lines)
    return ""


def cmd_save(args):
    root = repo_root(getattr(args, "project_dir", None))
    branch = current_branch(root)
    if branch in ("DETACHED", "HEAD"):
        print("⚠️  DETACHED HEAD 상태 — 브랜치를 먼저 체크아웃하세요.", file=sys.stderr)
        return 1
    facts = git_facts(root)

    done = args.done or "(미작성)"
    nxt = args.next or "(미작성)"
    summary = args.summary or "(미작성)"
    verify = args.verify or "(미작성)"
    review_ledger = _review_ledger_summary(root, branch)
    review_section = f"\n{review_ledger}\n" if review_ledger else ""

    body = f"""# 작업 핸드오프 — {branch}

> 갱신: {now_iso()} · 에이전트: {args.agent} · 머신: {machine_name()}
> ⚠️ 이 파일은 **커밋됨**. 이어받는 사람/툴은 먼저 이걸 읽고 **현재 git 상태와 대조**한 뒤 진행하세요.
> transcript 만 믿지 말 것 — git 사실이 우선입니다.

## 요약
{summary}

## 완료한 것
{done}

## 남은 것 / 다음 액션
{nxt}

## 검증 상태
{verify}
{review_section}

---
{AUTO_MARK}
## Git 사실 (자동 수집 @ {now_iso()})

- 브랜치: `{facts['branch']}`
- origin/main 대비 커밋:
```
{facts['ahead'] or '(없음)'}
```
- 변경 파일 (status -sb):
```
{facts['status'] or '(없음)'}
```
- diff --stat (unstaged):
```
{facts['stat_unstaged'] or '(없음)'}
```
- diff --stat (staged):
```
{facts['stat_staged'] or '(없음)'}
```
- 열린 PR: {facts['pr']}
"""

    target = handoff_path(root, branch)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w", encoding="utf-8") as f:
        f.write(body)
    rel = os.path.relpath(target, root)
    print(f"✅ 핸드오프 저장: {rel}")
    print("   → 커밋·푸시해야 다른 머신/사람/툴이 이어받습니다.")
    return 0


def cmd_load(args):
    root = repo_root(getattr(args, "project_dir", None))
    branch = current_branch(root)
    target = handoff_path(root, branch)
    out = []
    out.append(f"# 작업 이어받기 — 브랜치 `{branch}`")
    out.append("")
    out.extend(_target_lines(root, getattr(args, "project_dir", None)))
    if os.path.isfile(target):
        out.append(f"## 📄 커밋된 핸드오프 ({os.path.relpath(target, root)})")
        out.append("")
        with open(target, encoding="utf-8") as f:
            out.append(f.read().rstrip())
    else:
        out.append("## 📄 커밋된 핸드오프: 없음")
        out.append(f"   (이 브랜치엔 `{os.path.relpath(target, root)}` 가 아직 없음)")
    out.append("")
    out.append("---")
    out.extend(_facts_lines(git_facts(root), "## 🔎 현재 git 사실 (핸드오프와 대조용)"))
    out.append("")
    hints = transcript_hint(root)
    if hints:
        out.append("## 🧩 깊은 복구 (이 머신 한정)")
        for h in hints:
            out.append(f"- {h}")
    else:
        out.append("## 🧩 깊은 복구: 이 머신엔 로컬 transcript 없음 — 커밋된 핸드오프로만 진행")
    if args.deep or args.transcript:
        out.append("")
        out.extend(_format_claude_deep_recovery(root, transcript=args.transcript))
        # ⚠️ Codex 쪽도 반드시 함께 낸다. 예전엔 Claude 만 요약하고 Codex 는 힌트 한 줄로
        # 끝냈는데, 그러면 Codex 로 하던 작업을 이어받을 때 deep 이 답을 못 주고 사람·모델이
        # 로그를 직접 뒤지게 된다 — 손 탐색에는 프로젝트 스코핑이 없어서 남의 프로젝트
        # 세션을 직전 작업으로 오인했다(이슈 #95). --transcript 로 특정 파일을 지목한
        # 경우는 그 파일만 보겠다는 뜻이므로 건너뛴다.
        if not args.transcript:
            out.append("")
            out.extend(_format_codex_deep_recovery(root))
    print("\n".join(out))
    return 0


def _live_session_excludes(root, current):
    """현재 툴의 live 세션(지금 이 fw 를 부른 그 세션)을 배제할 식별자를 계산.
    반대 툴은 실행 중이 아니므로 배제하지 않는다(그 최신 로그가 진짜 직전 작업).
    반환: (claude_exclude_stem, codex_exclude_sid) — 해당 없으면 None.

    규칙: **live 세션을 이 프로젝트 로그에서 positive 식별할 때만 배제한다.** env 가 가리키는 id 가
    실제 프로젝트 로그와 매칭될 때만 그 id 를 반환하고, 매칭 안 되면 (None → 아무것도 안 숨김).
    - claude: env `CLAUDE_CODE_SESSION_ID`(=transcript 파일 stem) 가 이 프로젝트 transcript 중 하나와 일치할 때.
    - codex : env `CODEX_THREAD_ID`(추정: rollout session_meta.id) 또는 `CODEX_SESSION_ID` 가
      이 프로젝트 rollout 중 하나와 일치할 때.

    왜 매칭 안 되면 '아무것도 안 숨김'인가(=최신 배제 fallback 을 쓰지 않는가): env 가 무엇을 가리키는지
    확증 못 하는 상황(예: Codex 가 rollout id 와 다른 CODEX_THREAD_ID 를 export)에서 최신 로그를 무턱대고
    배제하면, 그 최신이 실은 복원해야 할 **직전 작업**일 때 그걸 숨긴다(더 나쁜 실패). 반대로 안 숨기면
    최악이라도 목록에 내 live 세션이 한 줄 더 보일 뿐이고, 이어받기는 현재 git 이 우선이라 안전하다."""
    claude_stem = codex_sid = None
    cur = (current or "").lower()
    if cur == "claude":
        env_stem = os.environ.get("CLAUDE_CODE_SESSION_ID")
        if env_stem:
            rows = _recent_claude_transcripts(root, limit=50)
            stems = {os.path.splitext(os.path.basename(r[2]))[0] for r in rows}
            if env_stem in stems:
                claude_stem = env_stem
    elif cur == "codex":
        # 현재 Codex 는 CODEX_THREAD_ID 를 export(추정: session_meta.id). CODEX_SESSION_ID 는 보조.
        # 두 후보를 모두 프로젝트 rollout id 와 대조한다 — `A or B` 로 하면 A 가 truthy 지만
        # 매칭 안 될 때 B 를 아예 안 보고 short-circuit 되어, B 가 맞는 env 에서 live 세션을 놓친다.
        candidates = [c for c in (os.environ.get("CODEX_THREAD_ID"),
                                  os.environ.get("CODEX_SESSION_ID")) if c]
        if candidates:
            rows = _recent_codex_rollouts(root, limit=50)
            ids = {_codex_rollout_meta(r[2])[0] for r in rows}
            for c in candidates:
                if c in ids:
                    codex_sid = c
                    break
    return claude_stem, codex_sid


def cmd_fw(args):
    """세션 로그(Claude .jsonl / Codex rollout)에서 작업을 자동 복원 — 툴 전환 이어받기.
    handoff-load 와 달리 명시적 save 없이도 로그로 복원한다(보조 경로). git 사실이 우선.

    소스 선택: --session(직접 지정) > --from(툴) > auto(양쪽 최신).
    렌더된 스킬은 **반대 툴**을 --from 기본값으로 넘긴다(Claude→codex, Codex→claude) —
    방금 켠 현재 세션 로그가 최신이라 자기 자신을 고르는 사고를 구조적으로 막는다."""
    root = repo_root(getattr(args, "project_dir", None))
    src = (args.from_tool or "auto").lower()
    limit = max(1, int(getattr(args, "limit", 1) or 1))

    out = [
        f"# 툴 전환 이어받기 (fw) — source: {src}",
        "",
        *_target_lines(root, getattr(args, "project_dir", None)),
        "> ⚠️ fw 는 **저장 안 한 세션 로그**에서 자동 복원하는 보조 경로다. 커밋된 핸드오프"
        "(`load`)가 있으면 그게 정본이고, **현재 git 상태가 로그보다 항상 우선**이다.",
        "",
    ]

    if args.session:
        # 포맷 자동 판별: 첫 줄이 session_meta 면 Codex rollout, 아니면 Claude .jsonl.
        sid, _cwd = _codex_rollout_meta(args.session)
        if sid:
            out.extend(_format_codex_deep_recovery(root, session=args.session))
        else:
            out.extend(_format_claude_deep_recovery(root, transcript=args.session))
    elif src == "codex":
        out.extend(_format_codex_deep_recovery(root, limit=limit))
    elif src == "claude":
        out.extend(_format_claude_deep_recovery(root, limit=limit))
    elif src == "both":  # 양쪽 로그를 한 번에 — 현재 툴의 live 세션만 배제
        claude_stem, codex_sid = _live_session_excludes(root, getattr(args, "current", None))
        out.extend(_format_codex_deep_recovery(root, limit=limit, exclude_sid=codex_sid))
        out.append("")
        out.extend(_format_claude_deep_recovery(root, limit=limit, exclude_stem=claude_stem))
    else:  # auto — 양쪽 통틀어 최신 세션 하나
        cand = [("claude",) + r for r in _recent_claude_transcripts(root, limit=1)]
        cand += [("codex",) + r for r in _recent_codex_rollouts(root, limit=1)]
        cand.sort(key=lambda t: t[1], reverse=True)  # t[1]=mtime
        if not cand:
            out.append("## 🧩 이 프로젝트의 최근 세션 로그 없음 (Claude·Codex 양쪽, 이 머신 한정)")
        elif cand[0][0] == "codex":
            out.extend(_format_codex_deep_recovery(root, session=cand[0][3]))
        else:
            out.extend(_format_claude_deep_recovery(root, transcript=cand[0][3]))

    out.append("")
    out.append("---")
    out.extend(_facts_lines(git_facts(root), "## 🔎 현재 git 사실 (로그와 대조 — git 우선)"))
    print("\n".join(out))
    return 0


def main():
    p = argparse.ArgumentParser(description="작업 핸드오프 (save/load/fw/history)")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("save", help="현재 작업 상태를 핸드오프 파일로 저장")
    s.add_argument("--agent", default=os.environ.get("HANDOFF_AGENT", "unknown"),
                   help="작성 에이전트 (claude|codex|사람이름). 기본 env HANDOFF_AGENT")
    s.add_argument("--summary", help="한두 줄 작업 요약")
    s.add_argument("--done", help="완료한 것 (마크다운 불릿 가능)")
    s.add_argument("--next", dest="next", help="남은 것/다음 액션 (마크다운 불릿 가능)")
    s.add_argument("--verify", help="검증 상태 (테스트/빌드/리뷰 결과)")
    s.add_argument("--project-dir", dest="project_dir",
                   help="핸드오프를 저장할 사용자 프로젝트 루트 절대경로. 생략 시 CLAUDE_PROJECT_DIR "
                        "env → cwd 의 git 루트 순. 스킬 폴더(플러그인 캐시)에서 실행할 땐 필수로 명시.")
    s.set_defaults(func=cmd_save)

    l = sub.add_parser("load", help="현재 브랜치 핸드오프 + git 사실 출력")
    l.add_argument("--deep", action="store_true",
                   help="같은 머신의 최근 Claude Code JSONL 을 짧게 요약해 이어받기 단서를 함께 출력")
    l.add_argument("--transcript",
                   help="직접 지정한 Claude Code JSONL 경로를 요약 (세션 UUID 대신 전체 경로 권장)")
    l.add_argument("--project-dir", dest="project_dir",
                   help="핸드오프를 찾을 사용자 프로젝트 루트 절대경로. 생략 시 CLAUDE_PROJECT_DIR "
                        "env → cwd 의 git 루트 순. 스킬 폴더(플러그인 캐시)에서 실행할 땐 필수로 명시.")
    l.set_defaults(func=cmd_load)

    fw = sub.add_parser("fw", help="세션 로그에서 작업 자동 복원 — 툴 전환 이어받기(저장 안 했어도)")
    fw.add_argument("--from", dest="from_tool", default="auto",
                    choices=["claude", "codex", "auto", "both"],
                    help="복원 소스 툴. 렌더된 스킬은 반대 툴을 기본 지정(Claude→codex, Codex→claude) "
                         "— 현재 세션 자기선택 방지. auto=양쪽 최신 하나. "
                         "both=Claude·Codex 양쪽 로그를 함께(현재 툴의 live 세션만 배제, --current 로 지정).")
    fw.add_argument("--current", choices=["claude", "codex"],
                    help="지금 fw 를 실행 중인 툴. --from both 에서 이 툴의 live 세션(방금 켠 현재 "
                         "세션)을 직전 작업으로 오인하지 않게 배제한다. 렌더된 스킬이 자동으로 넘긴다.")
    fw.add_argument("--session",
                    help="특정 세션 로그 경로 직접 지정 (Claude .jsonl 또는 Codex rollout). "
                         "포맷은 자동 판별.")
    fw.add_argument("--limit", type=int, default=1, help="요약할 최근 세션 수 (기본 1)")
    fw.add_argument("--project-dir", dest="project_dir",
                    help="프로젝트 루트 절대경로. 생략 시 CLAUDE_PROJECT_DIR env → cwd 의 git 루트 순. "
                         "스킬 폴더(플러그인 캐시)에서 실행할 땐 필수로 명시.")
    fw.set_defaults(func=cmd_fw)

    history = sub.add_parser("history", help="Claude·Codex 세션 로그 읽기 전용 목록·검색")
    history.add_argument("--from", dest="from_tool", default="both",
                         choices=["claude", "codex", "both"],
                         help="조회할 툴 (기본 both)")
    history.add_argument("--limit", type=int, default=20, help="최대 결과 수 (기본 20)")
    history.add_argument("--since", default="30d", help="조회 기간: 30m, 12h, 7d, 2w (기본 30d)")
    history.add_argument("--grep", help="후보 JSONL 전체에서 대소문자 무시 키워드 검색")
    history.add_argument("--no-content", action="store_true",
                         help="프롬프트 snippet을 숨기고 경로·메타데이터만 출력")
    history.add_argument("--json", action="store_true", help="JSON 출력")
    history.add_argument("--project-dir", dest="project_dir",
                         help="프로젝트 루트 절대경로. 플러그인 캐시에서 실행할 때 필수.")
    history.set_defaults(func=cmd_history)

    args = p.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
