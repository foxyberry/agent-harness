#!/usr/bin/env python3
"""
자가 개선 회고 잡 (self-improving retrospection job).

세션 트랜스크립트(.jsonl) 를 압축 → LLM 으로 분석 → 영속할 교훈을
`.claude/memory/_pending/` 에 "초안" 으로 저장한다. (사람이 다음 세션에서 승인)

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

PROMPT = """너는 "자가 개선 회고 시스템"이다. 아래는 한 작업 세션의 압축된 대화 트랜스크립트다.
이 세션에서 **앞으로 모든 세션에 영속될 가치가 있는 교훈**만 골라 memory 초안을 작성하라.

규칙:
- 사용자가 준 지적·교정·결정(특히 "~하지 마", "~로 해", 방식 변경)을 우선 추출.
- 이 세션에만 해당하는 일회성 사실(특정 PR 번호, 특정 파일 경로)은 제외.
- 일반화 가능하고 재사용되는 패턴/규칙만. 애매하면 빼라(보수적).
- 0~5개. 없으면 "초안 없음"이라고만 답하라.
- 각 초안은 아래 형식의 코드블록 하나로 (frontmatter + 본문):

```
---
name: <kebab-case-slug>
description: <한 줄 요약>
type: feedback | project | user | reference
---
<핵심 내용. feedback/project 면 **Why:** 와 **How to apply:** 줄 포함>
```

설명 없이 초안 코드블록들만 출력하라.

=== 압축 트랜스크립트 ===
"""


def _project_dir():
    return os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()


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

    text = BACKENDS[backend](PROMPT + body)
    drafts = _split_drafts(text)
    if not drafts:
        sys.stderr.write("[reflect] 초안 없음\n")
        return

    out_dir = os.path.join(_project_dir(), ".claude/memory/_pending")
    os.makedirs(out_dir, exist_ok=True)
    written = []
    for d in drafts:
        slug = _slug(d)
        path = os.path.join(out_dir, f"{slug}.md")
        # 같은 slug 초안이 이미 대기 중이면 덮어쓰지 않고 suffix 로 보존 — 미검토 초안 유실 방지.
        # (/memory-update 가 검토 시 중복을 병합하므로 누적돼도 안전하다.)
        i = 2
        while os.path.exists(path):
            path = os.path.join(out_dir, f"{slug}-{i}.md")
            i += 1
        open(path, "w", encoding="utf-8").write(d + "\n")
        written.append(os.path.basename(path))
    sys.stderr.write(
        f"[reflect] backend={backend} 트랜스크립트 {n}줄 → 초안 {len(written)}개: "
        f"{', '.join(written)}\n"
    )


if __name__ == "__main__":
    main()
