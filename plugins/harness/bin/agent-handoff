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
import socket
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
    # 머신 식별 (크로스머신 핸드오프 추적용). 플랫폼 무관하게 hostname.
    return socket.gethostname()


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
    """같은 머신에 로컬 transcript 가 있으면 '깊은 복구 가능' 힌트 반환."""
    home = os.path.expanduser("~")
    hints = []
    # Claude: ~/.claude/projects/<cwd '/'→'-'>/*.jsonl
    proj_key = _claude_project_key(root)
    claude_dir = os.path.join(home, ".claude", "projects", proj_key)
    if os.path.isdir(claude_dir):
        jsonls = [f for f in os.listdir(claude_dir) if f.endswith(".jsonl")]
        if jsonls:
            hints.append(
                f"Claude transcript {len(jsonls)}개 @ {claude_dir} "
                f"→ /fw-claude 또는 /continue-claude 로 깊은 복구 가능 (이 머신 한정)"
            )
    # Codex: ~/.codex/sessions/**/*.jsonl
    codex_dir = os.path.join(home, ".codex", "sessions")
    if os.path.isdir(codex_dir):
        found = False
        for _r, _d, files in os.walk(codex_dir):
            if any(f.endswith(".jsonl") for f in files):
                found = True
                break
        if found:
            hints.append(
                f"Codex session transcript 존재 @ {codex_dir} (이 머신 한정)"
            )
    return hints


def _claude_project_dir(root):
    """Claude Code project transcript dir for this repo, if present."""
    proj_key = _claude_project_key(root)
    return os.path.join(os.path.expanduser("~"), ".claude", "projects", proj_key)


def _claude_project_key(path):
    """Claude Code project dir key. Current Claude Code replaces path separators and dots."""
    return path.replace("/", "-").replace(".", "-")


def _recent_claude_transcripts(root, limit=2):
    """최근 Claude Code top-level transcript 목록. subagents 는 보조 로그라 기본 제외."""
    claude_dir = _claude_project_dir(root)
    if not os.path.isdir(claude_dir):
        return []
    rows = []
    try:
        for fn in os.listdir(claude_dir):
            if not fn.endswith(".jsonl"):
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
        with open(path, encoding="utf-8") as f:
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


def _format_claude_deep_recovery(root, limit=2, transcript=None):
    paths = []
    if transcript:
        paths = [(0, 0, os.path.expanduser(transcript))]
    else:
        paths = _recent_claude_transcripts(root, limit=limit)
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


def _recent_codex_rollouts(root, limit=2, days=30):
    """이 프로젝트(session_meta.cwd == root 또는 그 하위) 의 최근 Codex rollout
    [(mtime, size, path)]. 최근 `days` 일 날짜 디렉토리만 순회해 시작 비용을 제한한다
    (~/.codex/sessions 는 YYYY/MM/DD 로 분할 저장). +2일 버퍼: 자정 넘긴 세션 포함."""
    base = _codex_sessions_dir()
    if not os.path.isdir(base):
        return []
    today = datetime.now()
    date_dirs = [
        os.path.join(base, f"{d.year:04d}", f"{d.month:02d}", f"{d.day:02d}")
        for d in (today - timedelta(days=i) for i in range(days + 2))
    ]
    rows = []
    for dd in date_dirs:
        if not os.path.isdir(dd):
            continue
        try:
            names = os.listdir(dd)
        except OSError:
            continue
        for fn in names:
            if not (fn.startswith("rollout-") and fn.endswith(".jsonl")):
                continue
            fp = os.path.join(dd, fn)
            _sid, cwd = _codex_rollout_meta(fp)
            in_project = cwd == root or bool(cwd and cwd.startswith(root + os.sep))
            if not in_project:
                continue
            try:
                rows.append((os.path.getmtime(fp), os.path.getsize(fp), fp))
            except OSError:
                continue
    rows.sort(reverse=True)
    return rows[:limit]


def _summarize_codex_rollout(path):
    """Codex rollout JSONL 에서 이어받기 신호(최근 user/assistant 텍스트, 도구명)만 요약."""
    summary = {"last_users": [], "last_assistants": [], "last_tools": []}
    try:
        with open(path, encoding="utf-8") as f:
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


def _format_codex_deep_recovery(root, limit=1, session=None):
    if session:
        paths = [(0, 0, os.path.expanduser(session))]
    else:
        paths = _recent_codex_rollouts(root, limit=limit)
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


def _facts_lines(facts, header):
    """git_facts dict 를 사람이 읽는 마크다운 줄로 (load·fw 공용)."""
    return [
        header,
        f"- 브랜치: `{facts['branch']}`",
        "- origin/main 대비 커밋:", "```", facts["ahead"] or "(없음)", "```",
        "- 변경 파일 (status -sb):", "```", facts["status"] or "(없음)", "```",
        f"- 열린 PR: {facts['pr']}",
    ]


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
    print("\n".join(out))
    return 0


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
    p = argparse.ArgumentParser(description="작업 핸드오프 (save/load/fw)")
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
                    choices=["claude", "codex", "auto"],
                    help="복원 소스 툴. 렌더된 스킬은 반대 툴을 기본 지정(Claude→codex, Codex→claude) "
                         "— 현재 세션 자기선택 방지. auto=양쪽 최신.")
    fw.add_argument("--session",
                    help="특정 세션 로그 경로 직접 지정 (Claude .jsonl 또는 Codex rollout). "
                         "포맷은 자동 판별.")
    fw.add_argument("--limit", type=int, default=1, help="요약할 최근 세션 수 (기본 1)")
    fw.add_argument("--project-dir", dest="project_dir",
                    help="프로젝트 루트 절대경로. 생략 시 CLAUDE_PROJECT_DIR env → cwd 의 git 루트 순. "
                         "스킬 폴더(플러그인 캐시)에서 실행할 땐 필수로 명시.")
    fw.set_defaults(func=cmd_fw)

    args = p.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
