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
import fnmatch
import os
import re
import subprocess
import sys
import tempfile

# repo_identity 는 build.sh 가 이 훅과 같은 디렉토리에 co-locate 한다(reflect.py 와 동일 규약).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from repo_identity import ProjectMatcher
except ImportError:  # 단독 복사본 등 helper 부재 — 스윕만 비활성, 나머지 훅 기능은 유지
    ProjectMatcher = None
try:
    from hook_io import emit_context, project_dir as hook_project_dir, trace_entry
except ImportError:
    def emit_context(event, text):
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": event, "additionalContext": text}}))

    def hook_project_dir(data=None):
        return (os.environ.get("CLAUDE_PROJECT_DIR")
                or ((data or {}).get("cwd") if isinstance(data, dict) else None)
                or os.getcwd())

    def trace_entry(*_a, **_kw):
        pass

# "머지를 끝냈다"는 완료형만 매칭. 제안/질문/부정("머지하자/머지 언제해?/머지하지마",
# "is this merged?", "not merged yet")은 제외.
MERGE_DONE = re.compile(
    r"(머지|병합)\s*(을|를)?\s*(했|함|완료|끝|됐|되었)"
    r"|\b(merge\s+(is\s+)?done|merge\s+completed|it('?s| is| has)?\s+merged|pr\s+#?\d+\s+(is\s+)?merged)\b",
    re.I,
)

REMIND = (
    "머지된 PR{detail} 의 회고가 아직 진행되지 않았습니다. "
    "새 작업에 들어가기 전에 먼저 다음을 실행해 이번 작업의 교훈을 반영하세요:\n"
    "- /feedback-review — 받은 지적을 규칙이나 skill 로 승격할지 검토\n"
    "- /memory-update — 새로 알게 된 패턴·결정을 메모리에 영속화 (대기 초안 검토·승격 포함)"
)

# _pending 초안이 이만큼 쌓이면 머지 리마인더를 "지금 정리" 로 강하게 에스컬레이션한다.
DRAFT_BACKLOG_THRESHOLD = 8

# PR 세부 정보는 PR마다 `gh pr view` 한 번(최대 8초)이 필요하다. SessionStart/UserPromptSubmit
# 를 오래 막지 않도록 한 번에 일부만 처리하고, 나머지는 다음 훅 호출에서 이어간다.
PR_SCAN_MAX_PER_RUN = 3

# 회고 산출물 PR 이 다시 회고를 요구하는 루프를 막는 기본 예외.
# 프로젝트별로 .claude/memory/reflect-skip.json 에서 확장/override 가능.
DEFAULT_REFLECT_SKIP = {
    "paths": [
        ".claude/memory/**",
        ".claude/handoff/**",
        ".agents/skills/**",
    ],
    "labels": [
        "skip-reflect",
        "no-reflect",
    ],
    "commit_messages": [
        "[skip reflect]",
        "skip-reflect",
        "no-reflect",
    ],
}


def _auto_reflect_enabled():
    """자동 회고 잡(claude -p 스폰) opt-in 게이트. 기본 꺼짐 — 설치만으로 백그라운드
    LLM 잡이 뜨지 않게. HARNESS_AUTO_REFLECT 가 1/true/on 이면 켜짐."""
    return os.environ.get("HARNESS_AUTO_REFLECT", "").strip().lower() in ("1", "true", "on", "yes")


def _pending_drafts(project_dir):
    """_pending/ 아래 모든 초안(.md) 상대경로 목록. 하위 디렉토리까지 재귀 —
    reflect 가 결정 초안을 `_pending/decisions/` 에 넣으므로 non-recursive listdir 로는 놓친다."""
    d = _pending_dir(project_dir)
    out = []
    try:
        for root, _dirs, files in os.walk(d):
            for f in files:
                if f.endswith(".md"):
                    out.append(os.path.relpath(os.path.join(root, f), d))
    except Exception:
        return []
    return out


def _draft_count(project_dir):
    return len(_pending_drafts(project_dir))


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


# 커밋되면 안 되는 하네스 산출물. **엔진이 지킨다** — project-template 의 .gitignore 는
# 사용자가 복사해야 생기고, README 는 그 복사를 선택 단계로 안내한다. 안 복사한 사용자는
# `git add -A` 로 이것들을 커밋하게 된다.
LOCAL_EXCLUDE_ENTRIES = (
    ".claude/.cache/",              # 런타임 캐시·로그
    ".claude/memory/_pending/",     # 회고 초안 — 세션 대화에서 뽑은 것, 사람 검토 전
    ".claude/memory/_rejected.md",  # 폐기 기록 — 작업 습관·실수 이력에 가깝다(개인 tier)
)


def _gitignore_literal(path):
    """저장소 상대 경로를 gitignore glob이 아닌 literal 패턴으로 만든다.

    backslash를 먼저 이스케이프한 뒤 glob·주석·부정·공백 문법 문자를 이스케이프한다.
    공백은 끝에 있을 때만 필수지만 전부 처리하면 segment 위치와 무관하게 같은 규칙이 된다.
    """
    escaped = []
    for char in path:
        if char in "\\*?[]#! ":
            escaped.append("\\")
        escaped.append(char)
    return "".join(escaped)


def _ensure_local_cache_exclude(project_dir):
    """커밋되면 안 되는 하네스 산출물을 로컬 exclude에 보강한다.

    사용자의 tracked .gitignore는 수정하지 않는다. Git이 아니거나 read-only인 프로젝트는
    훅 실행을 막지 않도록 조용히 통과한다.

    ⚠️ 캐시만이 아니다. `_pending/` 은 **세션 대화에서 뽑은 초안**이고 `_rejected.md` 는
    **안 남기기로 한 교훈 목록** = 작업 습관·실수 이력이다. 공개 저장소면 그대로 공개된다.
    """
    try:
        result = subprocess.run(
            [
                "git",
                "rev-parse",
                "--git-path",
                "info/exclude",
                "--show-prefix",
            ],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=3,
        )
        lines = result.stdout.splitlines()
        if result.returncode != 0 or not lines:
            return
        path = lines[0]
        prefix = lines[1] if len(lines) > 1 else ""
        if not os.path.isabs(path):
            path = os.path.join(project_dir, path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        existing = ""
        if os.path.exists(path):
            with open(path, encoding="utf-8") as handle:
                existing = handle.read()
        have = set(existing.splitlines())
        entries = [_gitignore_literal(prefix + entry) for entry in LOCAL_EXCLUDE_ENTRIES]
        missing = [entry for entry in entries if entry not in have]
        if not missing:
            return
        with open(path, "a", encoding="utf-8") as handle:
            if existing and not existing.endswith("\n"):
                handle.write("\n")
            for entry in missing:
                handle.write(entry + "\n")
    except (OSError, subprocess.SubprocessError):
        pass


def _reflect_skip_config_path(project_dir):
    memory_dir = os.path.realpath(os.path.join(project_dir, ".claude/memory"))
    path = os.path.realpath(os.path.join(memory_dir, "reflect-skip.json"))
    if path == memory_dir or path.startswith(memory_dir + os.sep):
        return path
    return None


def _pending_dir(project_dir):
    return os.path.join(project_dir, ".claude/memory/_pending")


def _write_json_atomic(path, data):
    """같은 디렉터리에 임시 파일로 쓰고 rename 한다. rename 은 원자적이다.

    ⚠️ 이 훅은 세션 종료·호스트 타임아웃에 **언제든 죽을 수 있다.** 그냥 `open(path,"w")` 로
    쓰면 자르기와 쓰기 사이에서 죽었을 때 **잘린 파일**이 남고, 다음 실행이 그걸 읽는다.
    그 상태가 "손상" 이 아니라 "비어 있음" 으로 해석되면(과거에 그랬다) 회고 대상이 통째로
    다시 밀려든다.

    같은 디렉터리에 만드는 이유: `os.replace` 는 같은 파일시스템 안에서만 원자적이다.
    """
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _load_state(cache):
    """캐시 없으면 None(=최초), 있으면 {'seen': set, 'pending': list}.

    ⚠️ **손상도 None 이다.** 예전엔 파싱 실패 시 빈 상태를 돌려줬는데, 호출부는 None 만
    "최초 실행" 으로 보고 빈 seen 은 "아직 아무것도 회고 안 함" 으로 본다. 그래서 잘린 캐시
    하나가 **머지된 PR 30개를 전부 미회고로** 만들었다 — 설계가 막는다고 적어둔 바로 그 폭주다.

    "손상됨" 과 "없었음" 은 다른 사건이지만, **복구 방법은 같다** — 현재 상태를 조용히 시드하고
    과거를 캐지 않는다. 그래서 같은 값을 돌려주는 게 맞다.
    """
    if not os.path.exists(cache):
        return None
    try:
        with open(cache, encoding="utf-8") as f:
            d = json.load(f)
        if not isinstance(d, dict):
            raise ValueError("state must be an object")
        seen = d.get("seen", [])
        pending = d.get("pending", [])
        if not isinstance(seen, list) or not isinstance(pending, list):
            raise ValueError("seen and pending must be lists")
        if not all(isinstance(n, int) and not isinstance(n, bool) for n in seen + pending):
            raise ValueError("seen and pending must contain PR numbers")
        return {"seen": set(seen), "pending": list(pending)}
    except (json.JSONDecodeError, TypeError, ValueError):
        sys.stderr.write(
            "[pr-merge-reflect] 캐시가 손상돼 최초 실행처럼 다시 시드한다 "
            "(기존 pending 은 복구할 수 없음)\n"
        )
        return None
    except OSError:
        # 일시적인 읽기 실패를 손상으로 오판해 정상 캐시를 재시드로 덮어쓰지 않는다.
        sys.stderr.write("[pr-merge-reflect] 캐시를 읽지 못해 이번 상태 갱신을 건너뛴다\n")
        raise


def _save_state(cache, seen, pending):
    """seen 은 최근 200개만(무한 증가 방지), pending 은 전부 유지."""
    try:
        _write_json_atomic(cache, {
            "seen": sorted(set(seen), reverse=True)[:200],
            "pending": sorted(set(pending), reverse=True),
        })
    except Exception as exc:
        # 훅은 fail-open 이어야 하지만, 상태가 저장되지 않았다는 사실은 진단 가능해야 한다.
        sys.stderr.write(f"[pr-merge-reflect] 캐시 저장 실패: {type(exc).__name__}\n")


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


def _load_reflect_skip_config(project_dir):
    cfg = {k: list(v) for k, v in DEFAULT_REFLECT_SKIP.items()}
    path = _reflect_skip_config_path(project_dir)
    if not path or not os.path.exists(path):
        return cfg
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return cfg
        if data.get("defaults") is False:
            cfg = {"paths": [], "labels": [], "commit_messages": []}
        for key in ("paths", "labels", "commit_messages"):
            vals = data.get(key)
            if isinstance(vals, list):
                cfg[key].extend(v for v in vals if isinstance(v, str) and v.strip())
        for key in cfg:
            cfg[key] = list(dict.fromkeys(cfg[key]))
    except Exception:
        return cfg
    return cfg


def _pr_details(project_dir, num):
    """PR skip 판정에 필요한 세부 정보. gh/네트워크 실패 시 None."""
    try:
        r = subprocess.run(
            ["gh", "pr", "view", str(num), "--json", "files,labels,commits"],
            cwd=project_dir, capture_output=True, text=True, timeout=8,
        )
        if r.returncode != 0:
            return None
        data = json.loads(r.stdout)
        files = [
            f.get("path") for f in data.get("files", [])
            if isinstance(f, dict) and isinstance(f.get("path"), str)
        ]
        labels = [
            l.get("name") for l in data.get("labels", [])
            if isinstance(l, dict) and isinstance(l.get("name"), str)
        ]
        messages = []
        for c in data.get("commits", []) or []:
            if not isinstance(c, dict):
                continue
            msg = c.get("messageHeadline") or ""
            body = c.get("messageBody") or ""
            if msg or body:
                messages.append((msg + "\n" + body).strip())
        return {"files": files, "labels": labels, "commit_messages": messages}
    except Exception:
        return None


def _matches_any(value, patterns):
    return any(fnmatch.fnmatch(value, p) for p in patterns)


def _message_matches_any(message, patterns):
    for pattern in patterns:
        if not pattern:
            continue
        if pattern.startswith("[") and pattern.endswith("]"):
            if pattern in message:
                return True
        elif re.search(rf"(?<![\w-]){re.escape(pattern)}(?![\w-])", message):
            return True
    return False


def _should_skip_reflect(project_dir, num):
    """회고 산출물 PR 은 pending/reflect 대상에서 제외한다.

    판정 실패는 False(회고함)로 둔다. 자동화를 놓치는 것보다 실제 작업 회고를 빠뜨리지
    않는 쪽이 보수적이다.
    """
    cfg = _load_reflect_skip_config(project_dir)
    details = _pr_details(project_dir, num)
    if details is None:
        return False

    labels = {l.lower() for l in details["labels"]}
    label_patterns = [p.lower() for p in cfg["labels"]]
    if any(_matches_any(label, label_patterns) for label in labels):
        return True

    commit_patterns = [p.lower() for p in cfg["commit_messages"]]
    for message in details["commit_messages"]:
        low = message.lower()
        if _message_matches_any(low, commit_patterns):
            return True

    files = details["files"]
    path_patterns = cfg["paths"]
    if files and path_patterns and all(_matches_any(path, path_patterns) for path in files):
        return True

    return False


def _scan_reflectable(project_dir, nums, cache, seen, pending):
    """미확인 PR 을 제한된 수만 검사하고 PR마다 상태를 저장한다.

    `seen` 은 skip 판정을 마친 PR만 뜻한다. 아직 상한 밖인 PR까지 seen 으로 넣으면 다음
    호출에서도 검사되지 않아 영구 누락된다. 반대로 각 판정 직후 저장하면 훅이 중간에
    종료돼도 같은 네트워크 작업을 처음부터 반복하지 않는다.
    """
    processed = 0
    for num in nums:
        if num in seen:
            continue
        if processed >= PR_SCAN_MAX_PER_RUN:
            break
        if not _should_skip_reflect(project_dir, num):
            pending.append(num)
        seen.add(num)
        processed += 1
        _save_state(cache, seen, pending)
    return seen, pending


def _detail(pending, titles):
    if not pending:
        return ""
    parts = []
    for n in sorted(pending, reverse=True)[:5]:
        t = titles.get(n)
        parts.append(f"#{n} {t}".strip() if t else f"#{n}")
    return " — " + ", ".join(parts)


def _emit(event_name, text):
    emit_context(event_name, text)


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
    enc = project_dir.replace("/", "-").replace(".", "-")  # /a/b.c → -a-b-c
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
    drafts = _pending_drafts(project_dir)  # 재귀 — decisions/ 하위 초안 포함
    if not drafts:
        return
    escalate = " ⚠️ 누적이 많으니 새 작업 전에 정리 권장." if len(drafts) >= DRAFT_BACKLOG_THRESHOLD else ""
    _emit(
        "SessionStart",
        f"자가 개선 회고 초안 {len(drafts)}개가 `.claude/memory/_pending/` 에 대기 중입니다 "
        f"({', '.join(sorted(drafts)[:5])}).{escalate} 사용자에게 검토를 제안하세요 — "
        f"`/memory-update` 로 검토·승격(또는 폐기)합니다. 교훈은 auto-memory/MEMORY.md 로, "
        f"결정(ADR, `decisions/`) 초안은 공유 memory(`decisions/`+INDEX)로 정리됩니다.",
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


def _sweep_codex_sessions(project_dir, current_session_id=None):
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
    if not os.path.exists(_reflect_script()):
        return  # Codex 3a 번들은 자동 LLM 회고를 의도적으로 싣지 않는다.
    if ProjectMatcher is None:
        return
    import time
    base = os.path.expanduser("~/.codex/sessions")
    if not os.path.isdir(base):
        return
    try:
        now = time.time()
        recent_cutoff = now - CODEX_SWEEP_RECENT_DAYS * 86400
        idle_cutoff = now - CODEX_SWEEP_MIN_IDLE_MIN * 60  # 이보다 최근 수정이면 진행 중 가능 → 제외
        # 날짜 디렉토리(YYYY/MM/DD)만 훑으면 **오래 전 시작해 최근 resume 한 세션을 놓친다**
        # (시작일 기준으로 저장되므로). handoff.py 의 _recent_codex_rollouts 와 동일하게
        # 전체 트리를 훑되 mtime 으로 거른다 — 파일 열기는 mtime 통과분만이라 비용은 stat 수준.
        rollouts = []  # (mtime, path) — 최근 N일 & 충분히 idle(완료 추정) 한 것만
        for directory, _dirs, names in os.walk(base):
            for fn in names:
                if not (fn.startswith("rollout-") and fn.endswith(".jsonl")):
                    continue
                fp = os.path.join(directory, fn)
                try:
                    mt = os.path.getmtime(fp)
                except OSError:
                    continue
                if recent_cutoff <= mt <= idle_cutoff:
                    rollouts.append((mt, fp))
        rollouts.sort(reverse=True)  # 최신 우선

        # worktree 를 지금 관측해 alias 캐시에 남긴다 — 나중에 제거돼도 되짚을 수 있게.
        matcher = ProjectMatcher(project_dir)
        matcher.record_worktrees()

        seen_path = _codex_seen_path(project_dir)
        # ⚠️ first_run 을 **파일 존재**로 정하면 안 된다. 잘린 파일이 있으면 "최초 아님 +
        # 빈 seen" 이 되어 이미 회고한 rollout 을 다시 회고하고, 아래 저장이 새 sid 만 남겨
        # **이전 기록을 통째로 버린다.** 자가 치유가 안 되고 백로그를 걸어가며 중복을 만든다.
        # 읽기에 성공했을 때만 "최초 아님" 이다 — 손상은 최초와 같이 취급해 조용히 시드한다.
        seen_list = None
        if os.path.exists(seen_path):
            try:
                with open(seen_path, encoding="utf-8") as f:
                    seen_list = list(json.load(f))
            except Exception:
                sys.stderr.write("[pr-merge-reflect] codex seen 캐시가 손상돼 다시 시드한다\n")
        first_run = seen_list is None
        if first_run:
            seen_list = []
        seen = set(seen_list)  # 멤버십 조회용. seen_list 는 삽입(처리)순 — 캡 시 최신 유지

        # 프로젝트(cwd) 필터를 cap 보다 먼저 적용 — 다른 repo 세션에 밀려 이 repo 것이 누락되지
        # 않도록 14일치 전부의 meta 를 읽어 이 프로젝트 미회고만 모은다(최신순). 회고 수만 아래서 제한.
        fresh = []  # (sid, fp): 이 프로젝트 + 미회고
        for _, fp in rollouts:
            sid, cwd = _codex_meta(fp)
            # 경로 prefix 가 아니라 git 저장소 identity 로 판정 — worktree 가 프로젝트
            # 폴더 밖(`~/.codex/worktrees/`, 형제 `.agent-worktrees/`)에 있어도 잡힌다.
            if sid and sid != current_session_id and sid not in seen and matcher.belongs(cwd):
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
        _write_json_atomic(seen_path, seen_list[-500:])  # 삽입순 최신 500 유지(무한증가 방지)
    except Exception:
        pass


# ---------- 이벤트 핸들러 ----------

def _on_session_start(project_dir, cache, data=None):
    merged = _recent_merged(project_dir)
    if merged is not None:
        nums = [n for n, _ in merged]
        try:
            state = _load_state(cache)
            if state is None:
                # 최초 실행: 현재 머지 상태를 시드만 (과거 PR 무더기 적재 방지)
                _save_state(cache, set(nums), [])
            else:
                _scan_reflectable(
                    project_dir, nums, cache, set(state["seen"]), list(state["pending"])
                )
        except OSError:
            # 상태 파일의 일시적 I/O 실패는 이번 PR 갱신만 건너뛴다. 아래 초안 알림과
            # Codex 스윕은 독립 기능이므로 함께 막지 않는다.
            pass
    # 이전에 돌아간 잡이 남긴 초안이 있으면 검토 권고
    _announce_pending_drafts(project_dir)
    # 이 프로젝트의 미회고 Codex 단독 세션을 회고 (opt-in)
    _sweep_codex_sessions(project_dir, (data or {}).get("session_id"))


def _git_toplevel(path):
    """Codex payload cwd가 하위 디렉터리여도 프로젝트 캐시를 저장소 루트에 통일한다."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], cwd=path,
            capture_output=True, text=True, timeout=3,
        )
        top = result.stdout.strip()
        if result.returncode == 0 and top:
            return os.path.normpath(top)
    except Exception:
        pass
    return os.path.normpath(path)


def _resolved_project_dir(data):
    """Claude의 명시 경로는 보존하고, Codex payload cwd만 저장소 루트로 통일한다."""
    if os.environ.get("CLAUDE_PROJECT_DIR"):
        return os.path.normpath(hook_project_dir(data))
    return _git_toplevel(hook_project_dir(data))


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


def _merge_statement(cmd):
    """실제로 `gh pr merge` 로 시작하는 statement 를 반환 — `echo "gh pr merge 5"`
    나 `grep`, 주석 안의 문자열 매칭 오탐을 배제한다. `;`·개행·`&&`·`||`·`|` 로 분리해
    각 조각의 앞부분(선행 공백 무시)만 본다."""
    for stmt in re.split(r"[;\n]|&&|\|\|?", cmd):
        if re.match(r"\s*gh\s+pr\s+merge\b", stmt):
            return stmt
    return ""


def _looks_like_merge(cmd):
    return bool(_merge_statement(cmd))


def _on_post_tool(data, project_dir, cache):
    if data.get("tool_name") != "Bash":
        return
    cmd = data.get("tool_input", {}).get("command", "")
    stmt = _merge_statement(cmd)
    if not stmt:
        return
    # PR 번호는 플래그 앞/뒤 어디든 올 수 있다: `gh pr merge 42 --squash` / `gh pr merge --squash 42`.
    m = re.search(r"gh\s+pr\s+merge\b[^\d]*(\d+)", stmt)
    num = int(m.group(1)) if m else None
    # 실제 MERGED 인지 확인 후에만 적재·스폰. 번호 없는 `gh pr merge`(현재 브랜치)는 검증 불가라 보류
    # — SessionStart 스윕/사용자 "머지했어" 발화로 뒤늦게 잡힌다.
    if num is None or not _pr_is_merged(project_dir, num) or _should_skip_reflect(project_dir, num):
        return
    # 캐시는 SessionStart 시드로만 생성(무더기 보고 방지) → 없으면 적재 보류.
    if os.path.exists(cache):
        state = _load_state(cache)
        # 손상 캐시(None)는 빈 상태로 덮어쓰지 않는다. 다음 SessionStart 가 최근 머지
        # 전체를 조용히 재시드해야 과거 PR 이 호출마다 다시 pending 으로 들어오지 않는다.
        if state is not None:
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
                # 과거 PR 은 조용히 시드하되, 사용자가 방금 머지했다고 알려준 최신 PR 하나는
                # 실제 skip 판정을 거친다. 먼저 최신을 제외해 저장해야 중간 종료 시 누락되지 않는다.
                latest = [merged[0][0]] if merged else []
                seen = {n for n, _ in merged if n not in latest}
                pending = []
                _save_state(cache, seen, pending)
                seen, pending = _scan_reflectable(
                    project_dir, latest, cache, seen, pending
                )
                if pending:
                    titles = {n: t for n, t in merged}
                    _emit("UserPromptSubmit", _remind_text(project_dir, _detail(pending, titles)))
                    _spawn_reflect_job(data, project_dir)
                    _save_state(cache, seen, [])
                return
            _emit("UserPromptSubmit", _remind_text(project_dir, ""))
            _spawn_reflect_job(data, project_dir)
        else:
            seen, pending = set(state["seen"]), list(state["pending"])
            titles = {}
            if merged is not None:
                titles = {n: t for n, t in merged}
                seen, pending = _scan_reflectable(
                    project_dir, [n for n, _ in merged], cache, seen, pending
                )
            if pending:
                _emit("UserPromptSubmit", _remind_text(project_dir, _detail(pending, titles)))
                _spawn_reflect_job(data, project_dir)
            elif merged is None:
                _emit("UserPromptSubmit", _remind_text(project_dir, ""))
                _spawn_reflect_job(data, project_dir)
            _save_state(cache, seen, [])  # 전달 후 비움
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
    trace_entry(__file__, event)
    # normpath: 끝 슬래시 제거 등 정규화 (Codex in-project 매칭이 trailing sep 로 깨지지 않게).
    project_dir = _resolved_project_dir(data)
    cache = _cache_path(project_dir)

    # 이 프로젝트가 하네스 메모리 시스템을 안 쓰면(.claude/memory 없음) 전체 no-op.
    # 미사용 repo 의 매 세션 시작마다 gh 폴링(수 초 블록)·Codex 디렉토리 walk 가 도는 걸 막는다.
    if not os.path.isdir(os.path.join(project_dir, ".claude/memory")):
        sys.exit(0)

    try:
        _ensure_local_cache_exclude(project_dir)
        if event == "SessionStart":
            _on_session_start(project_dir, cache, data)
        elif event == "PostToolUse":
            _on_post_tool(data, project_dir, cache)
        elif event == "UserPromptSubmit":
            _on_user_prompt(data, project_dir, cache)
    except Exception:
        pass  # 어떤 경우에도 세션/프롬프트를 막지 않는다

    sys.exit(0)


if __name__ == "__main__":
    main()
