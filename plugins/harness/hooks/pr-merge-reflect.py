#!/usr/bin/env python3
"""
PR 머지 회고 hook — 머지가 일어났을 때 회고를 놓치지 않게 한다. 두 역할:

A) 리마인더 (미회고 PR 큐 'pending') — LLM 안 씀, 항상 켜짐:
   감지(조용히 적재): SessionStart 폴링(외부 머지 포함) · PostToolUse(직접 머지)
                      · UserPromptSubmit("머지했어" 발화)
   전달: 다음 발화 때 pending 있으면 "회고부터 하라" 지시 주입 후 큐 비움.

B) 자동 회고 잡 (co-located reflect.py) — **opt-in, 기본 꺼짐**:
   ⚠️ 이 잡은 `claude -p` 백그라운드 프로세스를 띄운다. 플러그인 설치만으로 모든
   프로젝트의 머지마다 조용히 LLM 잡이 뜨는 걸 막기 위해, 환경변수
   HARNESS_AUTO_REFLECT=1 이 설정된 경우에만 스폰한다. 켜지면:
   세션 내에서 머지가 확인되면 백그라운드로 잡을 띄워 현재 세션 트랜스크립트를
   분석 → .claude/memory/_pending/ 에 초안 저장. detached 라 세션을 닫아도 완료된다.
   SessionStart 에서 _pending 초안이 있으면(누가 만들었든) 검토를 권고한다.

재귀 방지: 잡이 backend=claude 일 때 중첩 `claude -p` 가 또 이 hook 을 띄운다.
REFLECT_JOB=1 이 설정돼 있으면 hook 전체를 no-op 한다.
gh/네트워크 실패 등은 모두 조용히 exit 0 (세션/프롬프트를 막지 않음).
.claude/memory 가 없는 프로젝트에서도 조용히 통과한다(모든 데이터 접근이 fail-open).

경로 규약(플러그인 배포): **스크립트**(reflect.py·compact_transcript.py)는 이 파일과
같은 디렉토리에 co-locate → dirname(__file__) 로 해석. **데이터**(memory·_pending·.cache)는
$CLAUDE_PROJECT_DIR 하위. 이 둘은 플러그인에서 서로 다른 위치다(스크립트=플러그인 루트,
데이터=프로젝트 루트) — 절대 혼동하지 말 것.
"""
import json
import os
import re
import subprocess
import sys

# "머지를 끝냈다"는 완료형만 매칭. 제안/질문/부정("머지하자/머지 언제해?/머지하지마")은 제외.
MERGE_DONE = re.compile(r"(머지|병합)\s*(을|를)?\s*(했|함|완료|끝|됐|되었)|\bmerged\b", re.I)

REMIND = (
    "머지된 PR{detail} 의 회고가 아직 진행되지 않았습니다. "
    "새 작업에 들어가기 전에 먼저 다음을 실행해 이번 작업의 교훈을 반영하세요:\n"
    "- /feedback-review — 받은 지적을 규칙이나 skill 로 승격할지 검토\n"
    "- /memory-update — 새로 알게 된 패턴·결정을 메모리에 영속화 (대기 초안 검토·승격 포함)"
)

# _pending 초안이 이만큼 쌓이면 머지 리마인더를 "지금 정리" 로 강하게 에스컬레이션한다.
DRAFT_BACKLOG_THRESHOLD = 8


def _auto_reflect_enabled():
    """자동 회고 잡(claude -p 스폰) opt-in 게이트. 기본 꺼짐 — 설치만으로 백그라운드
    LLM 잡이 뜨지 않게. HARNESS_AUTO_REFLECT 가 1/true/on 이면 켜짐."""
    return os.environ.get("HARNESS_AUTO_REFLECT", "").strip().lower() in ("1", "true", "on", "yes")


def _draft_count(project_dir):
    try:
        return len([f for f in os.listdir(_pending_dir(project_dir)) if f.endswith(".md")])
    except Exception:
        return 0


def _remind_text(project_dir, detail):
    """기본 회고 리마인더 + 초안 누적이 임계 이상이면 검토·승격 에스컬레이션 추가."""
    text = REMIND.format(detail=detail)
    n = _draft_count(project_dir)
    if n >= DRAFT_BACKLOG_THRESHOLD:
        text += (
            f"\n\n⚠️ reflect 자동 초안이 {n}개 누적됐습니다(임계 {DRAFT_BACKLOG_THRESHOLD}). "
            f"새 작업 전에 `/memory-update` 로 초안을 검토·승격(또는 폐기)해 _pending 을 정리하세요."
        )
    return text


def _cache_path(project_dir):
    return os.path.join(project_dir, ".claude/.cache/pr-merge-seen.json")


def _pending_dir(project_dir):
    return os.path.join(project_dir, ".claude/memory/_pending")


def _load_state(cache):
    """캐시 없으면 None(=최초), 있으면 {'seen': set, 'pending': list}."""
    if not os.path.exists(cache):
        return None
    try:
        with open(cache) as f:
            d = json.load(f)
        return {"seen": set(d.get("seen", [])), "pending": list(d.get("pending", []))}
    except Exception:
        return {"seen": set(), "pending": []}


def _save_state(cache, seen, pending):
    try:
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        with open(cache, "w") as f:
            # seen 은 무한 증가 방지로 최근 200개만, pending 은 전부 유지.
            json.dump({
                "seen": sorted(set(seen), reverse=True)[:200],
                "pending": sorted(set(pending), reverse=True),
            }, f)
    except Exception:
        pass


def _recent_merged(project_dir):
    """최근 머지된 PR [(번호, 제목)] 또는 실패 시 None."""
    try:
        r = subprocess.run(
            ["gh", "pr", "list", "--state", "merged", "--limit", "30",
             "--json", "number,title"],
            cwd=project_dir, capture_output=True, text=True, timeout=6,
        )
        if r.returncode != 0:
            return None
        return [(int(p["number"]), p.get("title", "")) for p in json.loads(r.stdout)]
    except Exception:
        return None


def _detail(pending, titles):
    if not pending:
        return ""
    parts = []
    for n in sorted(pending, reverse=True)[:5]:
        t = titles.get(n)
        parts.append(f"#{n} {t}".strip() if t else f"#{n}")
    return " — " + ", ".join(parts)


def _emit(event_name, text):
    print(json.dumps({
        "hookSpecificOutput": {"hookEventName": event_name, "additionalContext": text}
    }))


# ---------- 자동 회고 잡 (B) ----------

def _reflect_script():
    """co-located reflect.py 절대경로. 플러그인 배포 시 이 hook 과 같은 디렉토리에 있다.
    (tutti 원본은 project_dir 하위를 가정했으나, 플러그인에선 스크립트가 프로젝트 밖이다.)"""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "reflect.py")


def _transcript_path(data, project_dir):
    """현재 세션 트랜스크립트 .jsonl 경로. hook 입력의 transcript_path 우선."""
    tp = data.get("transcript_path")
    if tp and os.path.exists(tp):
        return tp
    sid = data.get("session_id")
    if not sid:
        return None
    enc = project_dir.replace("/", "-")  # /a/b → -a-b (Claude Code projects 디렉토리 규칙)
    cand = os.path.expanduser(f"~/.claude/projects/{enc}/{sid}.jsonl")
    return cand if os.path.exists(cand) else None


def _run_reflect(transcript, project_dir, label="claude"):
    """reflect.py 를 detached 실행 (fire-and-forget). Claude 트랜스크립트·Codex rollout 공용.

    stdout/stderr 를 .claude/.cache/reflect.log 에 남긴다(관측성): 시작 시각·label·transcript 와
    reflect.py 결과 요약([reflect] 초안 N개 / 초안 없음 / 에러)이 기록돼 사후 확인 가능.
    """
    script = _reflect_script()
    if not os.path.exists(script) or not transcript or not os.path.exists(transcript):
        return False  # 스폰 못 함 → 호출부가 seen 처리 안 하도록(재시도 여지)
    try:
        from datetime import datetime
        log_path = os.path.join(project_dir, ".claude/.cache/reflect.log")
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        logf = open(log_path, "a", encoding="utf-8")
        logf.write(f"\n==== {datetime.now():%Y-%m-%d %H:%M:%S} reflect 시작 [{label}] "
                   f"(transcript={os.path.basename(transcript)}) ====\n")
        logf.flush()
        subprocess.Popen(
            ["python3", script, "--transcript", transcript],
            cwd=project_dir,
            env={**os.environ, "REFLECT_JOB": "1"},  # 중첩 claude 의 hook no-op
            stdout=logf, stderr=logf,  # DEVNULL 대신 로그로 — 잡 실행/결과/에러 관측
            start_new_session=True,  # 세션 닫혀도 계속 실행
        )
        return True  # 스폰 성공(잡 자체 결과는 비동기 — reflect.log 로 확인)
    except Exception:
        return False


def _spawn_reflect_job(data, project_dir):
    """현재 Claude 세션 트랜스크립트로 회고 잡 실행. opt-in 꺼져 있으면 no-op."""
    if not _auto_reflect_enabled():
        return
    _run_reflect(_transcript_path(data, project_dir), project_dir, label="claude")


def _announce_pending_drafts(project_dir):
    d = _pending_dir(project_dir)
    if not os.path.isdir(d):
        return
    drafts = [f for f in os.listdir(d) if f.endswith(".md")]
    if not drafts:
        return
    escalate = " ⚠️ 누적이 많으니 새 작업 전에 정리 권장." if len(drafts) >= DRAFT_BACKLOG_THRESHOLD else ""
    _emit(
        "SessionStart",
        f"자가 개선 회고 초안 {len(drafts)}개가 `.claude/memory/_pending/` 에 대기 중입니다 "
        f"({', '.join(sorted(drafts)[:5])}).{escalate} 사용자에게 검토를 제안하세요 — "
        f"`/memory-update` 로 검토·승격(또는 폐기)하면 auto-memory + MEMORY.md 로 정리됩니다.",
    )


# ---------- Codex 단독 세션 회고 (SessionStart 스윕) ----------

CODEX_SWEEP_RECENT_DAYS = 14    # 최근 N일 rollout 만 — 이게 비용 상한(14일치 first-line 읽기)
CODEX_SWEEP_MIN_IDLE_MIN = 30   # 최근 N분 내 수정 = 진행 중일 수 있음 → 회고/seed 보류(부분 회고 방지)
CODEX_SWEEP_MAX_PER_RUN = 3     # 1회 스윕당 회고 스폰 상한(버스트 방지)


def _codex_seen_path(project_dir):
    return os.path.join(project_dir, ".claude/.cache/codex-reflect-seen.json")


def _codex_meta(rollout_path):
    """rollout 첫 줄(session_meta) → (session_id, cwd)."""
    try:
        with open(rollout_path, encoding="utf-8") as f:
            d = json.loads(f.readline())
        if d.get("type") == "session_meta":
            p = d.get("payload") or {}
            return p.get("id"), p.get("cwd")
    except Exception:
        pass
    return None, None


def _sweep_codex_sessions(project_dir):
    """이 프로젝트(cwd) 의 미회고 Codex rollout 을 찾아 reflect 스폰. opt-in 꺼져 있으면 no-op.

    - 최초 실행: 과거 무더기 회고 방지로 현재 것을 seen 시드만(회고 X).
    - 이후: 미회고 rollout 회고, 1회 상한(CODEX_SWEEP_MAX_PER_RUN), 나머지는 다음 스윕.
    - 진행 중(최근 수정) rollout 은 제외 — 부분 회고/조기 seen 방지(idle 가드).
    - cwd 가 project_dir 또는 그 하위(in-project worktree)면 매칭. **외부 worktree
      (Codex Desktop `~/.codex/worktrees/.../<repo>`)는 v1 미커버 — 정확 경로/하위만.**
    - Codex-inside-Claude 호출도 별도 rollout 이라 함께 잡힘 → Claude 회고와 일부 중복 가능(v1).
    - fire-and-forget — 스폰 성공 후 reflect.py 가 비동기 실패(백엔드 불가/transient 에러)하면 그 세션은
      재시도 안 됨(이미 seen). Claude 회고 경로와 동일한 한계. 완료-확인 후 seen 처리는 상태-콜백 후속 과제.
    """
    if not _auto_reflect_enabled():
        return
    import time
    base = os.path.expanduser("~/.codex/sessions")
    if not os.path.isdir(base):
        return
    try:
        from datetime import datetime, timedelta
        now = time.time()
        recent_cutoff = now - CODEX_SWEEP_RECENT_DAYS * 86400
        idle_cutoff = now - CODEX_SWEEP_MIN_IDLE_MIN * 60  # 이보다 최근 수정이면 진행 중 가능 → 제외
        # 세션은 YYYY/MM/DD 로 날짜 분할 저장 → 최근 날짜 디렉토리만 순회(전체 히스토리 walk 회피 = 시작 비용 상한).
        # +2일 버퍼: 자정 넘겨 이어진 세션(시작일 디렉토리는 더 과거)도 포함.
        today = datetime.now()
        date_dirs = [
            os.path.join(base, f"{d.year:04d}", f"{d.month:02d}", f"{d.day:02d}")
            for d in (today - timedelta(days=i) for i in range(CODEX_SWEEP_RECENT_DAYS + 2))
        ]
        rollouts = []  # (mtime, path) — 최근 N일 & 충분히 idle(완료 추정) 한 것만
        for dd in date_dirs:
            if not os.path.isdir(dd):
                continue
            for fn in os.listdir(dd):
                if not (fn.startswith("rollout-") and fn.endswith(".jsonl")):
                    continue
                fp = os.path.join(dd, fn)
                try:
                    mt = os.path.getmtime(fp)
                except Exception:
                    continue
                if recent_cutoff <= mt <= idle_cutoff:
                    rollouts.append((mt, fp))
        rollouts.sort(reverse=True)  # 최신 우선

        seen_path = _codex_seen_path(project_dir)
        first_run = not os.path.exists(seen_path)
        try:
            seen_list = list(json.load(open(seen_path))) if not first_run else []
        except Exception:
            seen_list = []
        seen = set(seen_list)  # 멤버십 조회용. seen_list 는 삽입(처리)순 — 캡 시 최신 유지

        # 프로젝트(cwd) 필터를 cap 보다 먼저 적용 — 다른 repo 세션에 밀려 이 repo 것이 누락되지
        # 않도록 14일치 전부의 meta 를 읽어 이 프로젝트 미회고만 모은다(최신순). 회고 수만 아래서 제한.
        fresh = []  # (sid, fp): 이 프로젝트 + 미회고
        for _, fp in rollouts:
            sid, cwd = _codex_meta(fp)
            in_project = cwd == project_dir or bool(cwd and cwd.startswith(project_dir + os.sep))
            if sid and in_project and sid not in seen:
                fresh.append((sid, fp))

        if first_run:
            # 시드만(과거 회고 X). fresh 는 최신순 → 오래된 것부터 append 해 최신이 끝에 오게(캡 시 최신 유지)
            for sid, _fp in reversed(fresh):
                if sid not in seen:
                    seen.add(sid); seen_list.append(sid)
        else:
            for sid, fp in fresh[:CODEX_SWEEP_MAX_PER_RUN]:
                if _run_reflect(fp, project_dir, label=f"codex:{sid[:8]}"):
                    seen.add(sid); seen_list.append(sid)  # 스폰 성공 시에만 seen — 실패는 다음 스윕 재시도

        os.makedirs(os.path.dirname(seen_path), exist_ok=True)
        json.dump(seen_list[-500:], open(seen_path, "w"))  # 삽입순 최신 500 유지(무한증가 방지)
    except Exception:
        pass


# ---------- 이벤트 핸들러 ----------

def _on_session_start(project_dir, cache):
    merged = _recent_merged(project_dir)
    if merged is not None:
        nums = [n for n, _ in merged]
        state = _load_state(cache)
        if state is None:
            # 최초 실행: 현재 머지 상태를 시드만 (과거 PR 무더기 적재 방지)
            _save_state(cache, set(nums), [])
        else:
            new = [n for n in nums if n not in state["seen"]]
            _save_state(cache, state["seen"] | set(nums), state["pending"] + new)
    # 이전에 돌아간 잡이 남긴 초안이 있으면 검토 권고
    _announce_pending_drafts(project_dir)
    # 이 프로젝트의 미회고 Codex 단독 세션을 회고 (opt-in)
    _sweep_codex_sessions(project_dir)


def _pr_is_merged(project_dir, num):
    """PR 번호가 실제 MERGED 인지 확인. gh/네트워크 실패는 False(보수적)."""
    try:
        state = subprocess.run(
            ["gh", "pr", "view", str(num), "--json", "state", "-q", ".state"],
            cwd=project_dir, capture_output=True, text=True, timeout=8,
        ).stdout.strip().upper()
        return state == "MERGED"
    except Exception:
        return False


def _looks_like_merge(cmd):
    """명령의 한 statement 가 실제로 `gh pr merge` 로 시작하는지 검사 — `echo "gh pr merge 5"`
    나 `grep`, 주석 안의 문자열 매칭 오탐을 배제한다. `;`·개행·`&&`·`||`·`|` 로 분리해
    각 조각의 앞부분(선행 공백 무시)만 본다."""
    for stmt in re.split(r"[;\n]|&&|\|\|?", cmd):
        if re.match(r"\s*gh\s+pr\s+merge\b", stmt):
            return True
    return False


def _on_post_tool(data, project_dir, cache):
    if data.get("tool_name") != "Bash":
        return
    cmd = data.get("tool_input", {}).get("command", "")
    if not _looks_like_merge(cmd):
        return
    # PR 번호는 플래그 앞/뒤 어디든 올 수 있다: `gh pr merge 42 --squash` / `gh pr merge --squash 42`.
    m = re.search(r"gh\s+pr\s+merge\b[^\d]*(\d+)", cmd)
    num = int(m.group(1)) if m else None
    # 실제 MERGED 인지 확인 후에만 적재·스폰. 번호 없는 `gh pr merge`(현재 브랜치)는 검증 불가라 보류
    # — SessionStart 스윕/사용자 "머지했어" 발화로 뒤늦게 잡힌다.
    if num is None or not _pr_is_merged(project_dir, num):
        return
    # 캐시는 SessionStart 시드로만 생성(무더기 보고 방지) → 없으면 적재 보류.
    if os.path.exists(cache):
        state = _load_state(cache) or {"seen": set(), "pending": []}
        _save_state(cache, state["seen"] | {num}, state["pending"] + [num])
    # 현재 세션이 작업 세션 → 자동 회고 잡 실행(opt-in)
    _spawn_reflect_job(data, project_dir)


def _on_user_prompt(data, project_dir, cache):
    prompt = data.get("prompt", "") or ""
    merge_done = bool(MERGE_DONE.search(prompt))
    state = _load_state(cache)

    if merge_done:
        # 사용자가 직접 "머지했다" — 최우선 신호. 현재 세션 == 작업 세션으로 보고 잡 실행.
        merged = _recent_merged(project_dir)
        if state is None:
            if merged is not None:
                _save_state(cache, {n for n, _ in merged}, [])
            _emit("UserPromptSubmit", _remind_text(project_dir, ""))
        else:
            seen, pending = set(state["seen"]), list(state["pending"])
            titles = {}
            if merged is not None:
                titles = {n: t for n, t in merged}
                pending += [n for n, _ in merged if n not in seen]
                seen |= {n for n, _ in merged}
            _emit("UserPromptSubmit", _remind_text(project_dir, _detail(pending, titles)))
            _save_state(cache, seen, [])  # 전달 후 비움
        _spawn_reflect_job(data, project_dir)
        return

    # 일반 프롬프트(새 작업 시작 등): 미회고 PR 이 쌓여 있으면 회고부터 (리마인더만).
    # 교차세션 케이스라 현재 트랜스크립트는 작업 세션이 아님 → 잡은 띄우지 않음.
    if state and state["pending"]:
        _emit("UserPromptSubmit", _remind_text(project_dir, _detail(state["pending"], {})))
        _save_state(cache, state["seen"], [])


def main():
    # 재귀 방지: 회고 잡(backend=claude) 내부의 중첩 claude → 이 hook 전체 no-op
    if os.environ.get("REFLECT_JOB"):
        sys.exit(0)

    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    event = data.get("hook_event_name", "")
    # normpath: 끝 슬래시 제거 등 정규화 (Codex in-project 매칭이 trailing sep 로 깨지지 않게).
    project_dir = os.path.normpath(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    cache = _cache_path(project_dir)

    # 이 프로젝트가 하네스 메모리 시스템을 안 쓰면(.claude/memory 없음) 전체 no-op.
    # 미사용 repo 의 매 세션 시작마다 gh 폴링(수 초 블록)·Codex 디렉토리 walk 가 도는 걸 막는다.
    if not os.path.isdir(os.path.join(project_dir, ".claude/memory")):
        sys.exit(0)

    try:
        if event == "SessionStart":
            _on_session_start(project_dir, cache)
        elif event == "PostToolUse":
            _on_post_tool(data, project_dir, cache)
        elif event == "UserPromptSubmit":
            _on_user_prompt(data, project_dir, cache)
    except Exception:
        pass  # 어떤 경우에도 세션/프롬프트를 막지 않는다

    sys.exit(0)


if __name__ == "__main__":
    main()
