#!/usr/bin/env python3
"""
자가 개선 회고 잡 (self-improving retrospection job).

세션 트랜스크립트(.jsonl) 를 압축 → LLM 으로 분석 → 두 종류의 "초안" 을 저장한다:
  - 교훈 memory  → `.claude/memory/_pending/`
  - 의사결정 ADR → `.claude/memory/_pending/decisions/` (proposed_chain/supersedes 는 제안만)
(사람이 다음 세션에서 `/memory-update` 로 검토·승격. 체인 배정은 사람이 확정한다.)

백엔드는 플러그형 — REFLECT_BACKEND 환경변수로 선택 (기본 claude):
  - claude   : 로컬 `claude -p` (구독 사용, 키 불필요, 최고 품질)  ← 기본
  - deepseek : DeepSeek API (DEEPSEEK_API_KEY 필요, 저렴/빠름)
  - ollama   : 로컬 ollama (REFLECT_OLLAMA_MODEL, 오프라인/무료, 품질↓)

사용:
  python3 reflect.py --transcript <session.jsonl> [--backend claude|deepseek|ollama]

주의: claude 백엔드는 중첩 `claude -p` 가 또 hook 을 띄우는 재귀를 막기 위해
자식 프로세스에 REFLECT_JOB=1 을 넣는다. hook(pr-merge-reflect.py)은 이 값을
보면 no-op 한다.

이 스크립트는 hook(pr-merge-reflect.py)과 같은 디렉토리에 co-locate 되어야 한다
(compact_transcript.py 도 같은 디렉토리). 플러그인 배포 시 스크립트 위치와
프로젝트 위치가 분리되므로, hook 은 이 파일을 dirname(__file__) 로 찾는다.
"""
import json
import os
import re
import subprocess
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compact_transcript import compact  # noqa: E402

# 생성기 공유 — ADR 초안 계약(게이트 + frontmatter 필드 + 본문 섹션).
# reflect(세션 회고)·mine(git 소급) 두 생성기가 이걸 합성해 쓴다. 둘 다 같은 _split_drafts →
# 같은 _pending/decisions 라우팅 → 같은 /memory-update 승격 경로를 타므로, 필드가 어긋나면
# 초안이 잘못 라우팅된다. 계약 정의는 여기 한 곳에만 둔다(이슈 #19 재발 방지).
ADR_DRAFT_CONTRACT = """\
"왜 그렇게 했나"가 중요한 **결정**만. 반드시 게이트를 통과해야 한다:
- **안 고른 대안(Alternatives)** 과 **결과(Consequence)** 가 둘 다 있어야 ADR 이다. 없으면 ADR 아님 → 교훈 memory 로 돌리거나 버려라.
- 기준: 기각한 대안이 있거나 / 방향을 바꿨거나 / 되돌리기 비싼 결정. **0~3개, 각각 하나의 결정만(작게)**.
- **체인 배정은 확정하지 말고 제안만** 하라 — 아래 "기존 결정 체인 인덱스"를 참고해, 이어지는 축이면 그 chain slug 를, 새 축이면 `new:<이름>` 을 쓴다. 확신 없으면 confidence 를 낮춰라.
- 각 초안은 코드블록 하나:

```
---
name: <kebab-case-slug>
description: <한 줄 요약 — INDEX/검색 요약에 쓰인다. 꼭 채운다>
type: decision
proposed_chain: <기존 chain slug 또는 new:새이름>
proposed_supersedes: [<기존 id>, ...]   # 이 결정이 대체한 이전 결정 id. 없으면 []
confidence: high | medium | low          # chain/supersedes 제안의 확신도
keywords: [<검색어>, ...]                 # 검색 표면 — 꼭 채운다
---
## Context
## Decision
## Alternatives
## Consequence
## Evidence
```"""


PROMPT = ("""너는 "자가 개선 회고 시스템"이다. 아래는 한 작업 세션의 압축된 대화 트랜스크립트다.
여기서 **두 종류**를 각각 뽑아 초안을 작성하라: (A) 영속할 교훈(memory), (B) 중요한 의사결정(ADR).

## (A) 교훈 memory
- 사용자가 준 지적·교정·결정(특히 "~하지 마", "~로 해", 방식 변경)을 우선 추출.
- 이 세션에만 해당하는 일회성 사실(특정 PR 번호, 특정 파일 경로)은 제외. 일반화되는 패턴만. 애매하면 빼라.
- **아래 "이미 폐기한 초안" 목록을 먼저 본다.** 같은 얘기면 다시 만들지 마라 — 사람이 이미
  보고 안 남기기로 한 것이다. 단어가 달라도 같은 교훈이면 같은 것으로 친다.
  ⚠️ 금지 목록이 아니다. 그 사이에 **같은 일이 반복돼 값어치가 생겼다면** 다시 올려도 된다 —
  대신 초안 안에 **무엇이 달라졌는지**(몇 번 더 반복됐는지, 어떤 비용이 났는지)를 적어라.
- 0~5개. 각 초안은 코드블록 하나:

```
---
name: <kebab-case-slug>
description: <한 줄 요약>
type: feedback | project | user | reference
---
<핵심 내용. feedback/project 면 **Why:** 와 **How to apply:** 줄 포함>
```

## (B) 의사결정 ADR
""" + ADR_DRAFT_CONTRACT + """

설명 없이 (A)·(B) 초안 코드블록들만 출력하라. 뽑을 게 없으면 아무것도 출력하지 마라.
""")


def _project_dir():
    return os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()


def _rejected_index(project_dir):
    """사람이 이미 폐기한 초안 목록 — LLM 이 같은 걸 또 만들지 않게 프롬프트에 넣는다.

    ## 왜 이게 필요한가

    초안을 폐기하면 파일이 지워진다. **거절했다는 사실이 어디에도 안 남는다.** 다음 세션이
    같은 트랜스크립트를 읽고 같은 교훈을 뽑아 같은 초안을 또 만든다. 사람은 또 버린다.
    백로그가 커질수록 이 비용이 매번 반복된다(이슈 #109).

    ## 왜 정규식이나 유사도 계산이 아닌가

    "같은 교훈인가"는 문자열 비교로 안 갈린다 — 같은 얘기를 다른 말로 쓰면 못 잡는다.
    그런데 그 판단을 **이미 LLM 이 하고 있다.** `_decisions_index` 가 기존 ADR 을 프롬프트에
    넣어 체인 제안을 시키는 것과 똑같은 방식으로, 폐기 목록을 보여주면 알아본다.
    별도 기계장치가 필요 없다.

    ## 왜 하드 필터가 아니라 프롬프트 힌트인가

    한 번 거절했다고 **영원히** 막으면 그게 또 버그다 — 7월에 "너무 사소하다"고 버린 교훈이
    9월에 세 번 더 반복되면 남길 값어치가 생긴다. 프롬프트에 넣으면 LLM 이 정황을 보고 다시
    올릴 수 있다. 그래서 만료 규칙이 필요 없다.

    파일이 없으면 `(아직 없음)`. `_decisions_index` 와 같이 **읽기만** 한다.
    """
    path = os.path.join(project_dir, ".claude/memory/_rejected.md")
    try:
        text = open(path, encoding="utf-8").read()
    except OSError:
        return "(아직 없음)"
    # ⚠️ 주석 블록을 **먼저** 걷어낸다. 템플릿이 예시 항목을 `<!-- ... -->` 안에 넣는데,
    # 줄 단위로만 보면 그 예시가 `- ` 로 시작해 **진짜 폐기 기록으로 잡힌다.** 템플릿을
    # 복사한 프로젝트마다 있지도 않은 거절이 프롬프트에 주입돼, 비슷한 교훈이 조용히 막힌다.
    # (`_decisions_index` 가 README·EXAMPLE 파일을 거르는 것과 같은 이유다.)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    # 항목은 `- ` 로 시작하는 줄. 나머지(제목·설명문)는 무시한다.
    rows = [l.rstrip() for l in text.splitlines() if l.startswith("- ")]
    if not rows:
        return "(아직 없음)"
    # 추가 전용 파일이라 **뒤쪽이 최신**이다. 넘치면 오래된 앞쪽을 버린다 — 최근 거절일수록
    # 다시 생성될 확률이 높다.
    cap = 50
    truncated = len(rows) > cap
    out = "\n".join(rows[-cap:])
    if truncated:
        out += f"\n(… 오래된 {len(rows) - cap}건 생략)"
    return out


def _decisions_index(project_dir):
    """기존 결정 ADR 들의 요약 인덱스(chain·id·keywords) — LLM 이 proposed_chain/proposed_supersedes
    를 제안할 수 있게 프롬프트에 넣는다. 없으면 '(아직 없음)'.
    이건 프로젝트 데이터(.claude/memory/decisions/)를 **읽기만** 한다 — 엔진에 프로젝트 특정
    하드코딩을 넣지 않는다(하네스 엔진/데이터 분리)."""
    ddir = os.path.join(project_dir, ".claude/memory/decisions")
    if not os.path.isdir(ddir):
        return "(아직 없음)"
    rows = []  # (mtime, block)
    for fn in os.listdir(ddir):
        # README(스키마 문서)와 예시 ADR(EXAMPLE)은 자동화 입력에서 제외 — 템플릿을 그대로
        # 복사한 새 프로젝트에서 예시가 "실제 기존 체인"으로 LLM 에 주입돼 supersedes 후보로
        # 제안되는 걸 막는다.
        if not fn.endswith(".md") or fn == "README.md" or "EXAMPLE" in fn.upper():
            continue
        fp = os.path.join(ddir, fn)
        try:
            head = open(fp, encoding="utf-8").read(2000)
            mt = os.path.getmtime(fp)
        except OSError:
            continue
        parts = head.split("---", 2)
        block = parts[1] if len(parts) >= 3 else head
        if not _is_decision(block):  # 라우팅과 동일 normalize (quote/주석/대소문자)
            continue
        rows.append((mt, block))
    if not rows:
        return "(아직 없음)"
    # 파일명이 아니라 mtime 최신순으로 정렬 후 상한 — 파일명은 설명적이라 정렬해도 시간·관련성이
    # 아니어서, 결정이 많아지면 active(최근) 체인이 상한에 밀려 조용히 사라질 수 있다. 최근 것 우선.
    rows.sort(key=lambda r: r[0], reverse=True)
    cap = 50
    truncated = len(rows) > cap
    blocks = [b for _mt, b in rows[:cap]]
    # 단방향 supersedes 모델: superseded_by 는 저장 안 하고 여기(조회 시점)서 계산한다.
    # 다른 결정이 supersedes 로 무는 id 는 "대체됨" 으로 표시(active 후보 오인 방지).
    superseded = set()
    for b in blocks:
        superseded |= set(_fm_list(b, "supersedes"))
    lines = []
    for b in blocks:
        _id = _fm(b, "id") or "?"
        status = _fm(b, "status").split("#", 1)[0].strip().strip("\"'").lower()
        if _id in superseded:
            mark = " (superseded)"
        elif status == "rejected":
            mark = " (rejected)"  # 기각된 결정 — 계속·대체 후보 아님
        else:
            mark = ""
        lines.append(
            f"- chain={_fm(b, 'chain') or '?'} | id={_id}{mark} | "
            f"{_fm(b, 'description') or _fm(b, 'name')} | keywords={_fm(b, 'keywords')}"
        )
    if truncated:
        lines.append(f"- … (결정 {len(rows)}개 중 최근 {cap}개만 표시)")
    return "\n".join(lines)


def _fm(block, key):
    """frontmatter 단일라인 값 (없으면 '')."""
    m = re.search(rf"^{key}:\s*(.+)$", block, re.M)
    return m.group(1).strip() if m else ""


def _fm_list(block, key):
    """frontmatter 인라인 리스트(`key: [a, b]`) → [a, b]. 없으면 []."""
    m = re.search(rf"^{key}:\s*\[(.*?)\]", block, re.M)
    if not m:
        return []
    return [x.strip().strip("\"'") for x in m.group(1).split(",") if x.strip()]


def _is_decision(block):
    """frontmatter type 이 decision 인가. quote/인라인주석/대소문자 변형까지 관대하게 —
    안 그러면 `type: "decision"` 같은 유효 변형이 _pending/ 로 잘못 라우팅돼 소비자가 못 잡는다."""
    m = re.search(r"^type:\s*(.+)$", block, re.M)
    if not m:
        return False
    val = m.group(1).split("#", 1)[0].strip().strip("\"'").lower()
    return val == "decision"


# ---------- 백엔드 ----------

def _backend_claude(prompt):
    env = {**os.environ, "REFLECT_JOB": "1"}  # 재귀 방지: 중첩 claude 의 hook no-op
    r = subprocess.run(
        ["claude", "-p", prompt],
        capture_output=True, text=True, timeout=300, env=env,
    )
    if r.returncode != 0:
        raise RuntimeError(f"claude -p 실패: {r.stderr[:300]}")
    return r.stdout


def _backend_deepseek(prompt):
    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        raise RuntimeError("DEEPSEEK_API_KEY 없음")
    model = os.environ.get("REFLECT_DEEPSEEK_MODEL", "deepseek-chat")
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "temperature": 0.3,
    }).encode()
    req = urllib.request.Request(
        "https://api.deepseek.com/chat/completions",
        data=payload,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.load(r)["choices"][0]["message"]["content"]


def _backend_ollama(prompt):
    model = os.environ.get("REFLECT_OLLAMA_MODEL", "qwen2.5:14b")
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    payload = json.dumps({"model": model, "prompt": prompt, "stream": False}).encode()
    req = urllib.request.Request(
        f"{host}/api/generate",
        data=payload, headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.load(r)["response"]


BACKENDS = {
    "claude": _backend_claude,
    "deepseek": _backend_deepseek,
    "ollama": _backend_ollama,
}


# ---------- 출력 파싱 → 초안 파일 ----------

def _split_drafts(text):
    """LLM 출력에서 frontmatter 를 가진 ``` 블록들을 추출."""
    blocks = re.findall(r"```[a-zA-Z]*\n(.*?)```", text, re.S)
    return [b.strip() for b in blocks if "name:" in b and re.search(r"^type:", b, re.M)]


def _slug(block):
    m = re.search(r"^name:\s*(.+)$", block, re.M)
    s = (m.group(1).strip() if m else "draft")
    return re.sub(r"[^a-z0-9-]", "-", s.lower())[:60] or "draft"


def main():
    args = sys.argv[1:]

    def _flag_value(flag):
        """--flag 뒤의 값. 플래그가 없거나 값이 안 붙으면 None (IndexError 방지)."""
        if flag in args:
            i = args.index(flag)
            if i + 1 < len(args):
                return args[i + 1]
        return None

    transcript = _flag_value("--transcript")
    if transcript is None:
        sys.exit("usage: reflect.py --transcript <session.jsonl> [--backend claude|deepseek|ollama]")
    backend = _flag_value("--backend") or os.environ.get("REFLECT_BACKEND", "claude")
    if backend not in BACKENDS:
        sys.exit(f"unknown backend: {backend}")
    if not os.path.exists(transcript):
        sys.exit(f"transcript 없음: {transcript}")

    body, n = compact(transcript)
    if not body.strip():
        sys.exit(0)  # 빈 세션 → 조용히

    project_dir = _project_dir()
    prompt = (
        PROMPT
        + "\n=== 이미 폐기한 초안 (같은 얘기면 다시 만들지 말 것) ===\n"
        + _rejected_index(project_dir)
        + "\n\n=== 기존 결정 체인 인덱스 (proposed_chain/proposed_supersedes 제안에 참고) ===\n"
        + _decisions_index(project_dir)
        + "\n\n=== 압축 트랜스크립트 ===\n"
        + body
    )
    text = BACKENDS[backend](prompt)
    drafts = _split_drafts(text)
    if not drafts:
        sys.stderr.write("[reflect] 초안 없음\n")
        return

    pending = os.path.join(project_dir, ".claude/memory/_pending")
    written = []
    for d in drafts:
        slug = _slug(d)
        # 결정(ADR) 초안은 _pending/decisions/ 로, 교훈 memory 는 _pending/ 로 분리 라우팅.
        target = os.path.join(pending, "decisions") if _is_decision(d) else pending
        os.makedirs(target, exist_ok=True)
        path = os.path.join(target, f"{slug}.md")
        # 같은 slug 초안이 이미 대기 중이면 덮어쓰지 않고 suffix 로 보존 — 미검토 초안 유실 방지.
        # (/memory-update 가 검토 시 중복을 병합하므로 누적돼도 안전하다.)
        i = 2
        while os.path.exists(path):
            path = os.path.join(target, f"{slug}-{i}.md")
            i += 1
        open(path, "w", encoding="utf-8").write(d + "\n")
        written.append(os.path.relpath(path, pending))
    sys.stderr.write(
        f"[reflect] backend={backend} 트랜스크립트 {n}줄 → 초안 {len(written)}개: "
        f"{', '.join(written)}\n"
    )


if __name__ == "__main__":
    main()
