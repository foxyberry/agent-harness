#!/usr/bin/env python3
"""
의사결정 소급 마이닝 (decision back-mining).

git 히스토리 슬라이스(커밋 메시지 본문)를 LLM 으로 분석 → 이미 내려진 결정을
ADR 초안으로 소급 추출 → reflect 와 **같은 승격 경로**(`_pending/decisions/` →
`/memory-update` 1.6)에 떨군다.

reflect.py 의 초안 계약(`ADR_DRAFT_CONTRACT`)·백엔드·파싱·라우팅을 재사용한다 —
입력이 "세션 트랜스크립트" 대신 "git 슬라이스"인 **또 다른 초안 생성기**일 뿐이다.
(설계: docs/decision-mining.md, 이슈 #21)

사용:
  python3 mine.py <rev-range> [--backend claude|deepseek|ollama]
  예) python3 mine.py origin/main~20..origin/main
      python3 mine.py <merge_commit>^..<merge_commit>   # 단일 PR 슬라이스

한계(설계에 못 박음):
  - 커밋에 "왜"가 안 적혀 있으면 초안을 만들지 않는다(빈 rationale 발명 = 가짜 역사).
  - chain·supersedes 는 proposed_* 로만 — 사람이 /memory-update 로 확정(positive-only 계승).
  - Codex 훅은 defer 상태라 이 스크립트도 Claude 어댑터에만 배포된다(reflect.py 와 동일).
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from reflect import (  # noqa: E402
    BACKENDS,
    ADR_DRAFT_CONTRACT,
    _decisions_index,
    _split_drafts,
    _slug,
    _is_decision,
    _project_dir,
)

MINE_PROMPT = ("""너는 "의사결정 고고학자(decision archaeologist)"다. 아래는 한 저장소의
git 히스토리 슬라이스(커밋 메시지 모음)다. 여기서 **이미 내려진 중요한 의사결정(ADR)** 을
소급 복원해 초안으로 작성하라.

- **커밋 메시지에 "왜(rationale)" 가 실제로 적혀 있을 때만** 뽑아라. 안 적혀 있으면
  이유를 **발명하지 마라** — 그건 가짜 역사다. 신호 없는 커밋은 조용히 건너뛴다.
- "무엇을 바꿨나"(기능·리팩터 나열)는 ADR 이 아니다. 기각한 대안·방향 전환·되돌리기 비싼
  선택처럼 **"왜 그렇게 했나"가 근거와 함께 드러난 것**만.
- Evidence 섹션엔 근거가 된 커밋 해시(짧은 형태)를 적어라.

""" + ADR_DRAFT_CONTRACT + """

설명 없이 초안 코드블록들만 출력하라. 뽑을 게 없으면 아무것도 출력하지 마라.
""")


def git_slice(root, rev_range):
    """rev_range 안 커밋들의 메시지(제목+본문)를 마이닝 입력 텍스트로 압축.

    diff 는 넣지 않는다 — "왜"는 코드가 아니라 (있다면) 메시지에 있다. 입력을 rev_range 로
    묶어 firehose 를 **슬라이스**한다(전체 히스토리 통째 금지). 반환: (텍스트, 커밋수)."""
    fmt = "%H%x1f%ad%x1f%s%x1f%b%x1e"  # x1f=필드, x1e=레코드 구분자
    r = subprocess.run(
        ["git", "-C", root, "log", "--no-merges", "--date=short", f"--format={fmt}", rev_range],
        capture_output=True, text=True, timeout=60,
    )
    if r.returncode != 0:
        sys.exit(f"git log 실패: {r.stderr.strip()[:300]}")
    records = [rec for rec in r.stdout.split("\x1e") if rec.strip()]
    lines = []
    for rec in records:
        parts = rec.strip().split("\x1f")
        if len(parts) < 4:
            continue
        h, ad, subj, body = parts[0][:9], parts[1], parts[2], parts[3].strip()
        lines.append(f"### {h} ({ad}) {subj}")
        if body:
            lines.append(body)
    return "\n".join(lines), len(records)


def main():
    args = sys.argv[1:]
    if not args or args[0].startswith("-"):
        sys.exit("usage: mine.py <rev-range> [--backend claude|deepseek|ollama]")
    rev_range = args[0]
    backend = "claude"
    if "--backend" in args:
        i = args.index("--backend")
        if i + 1 < len(args):
            backend = args[i + 1]
    if backend not in BACKENDS:
        sys.exit(f"unknown backend: {backend}")

    root = _project_dir()
    body, n = git_slice(root, rev_range)
    if not body.strip():
        sys.exit(f"빈 슬라이스 — '{rev_range}' 에 (머지 제외) 커밋 없음")

    prompt = (
        MINE_PROMPT
        + "\n=== 기존 결정 체인 인덱스 (proposed_chain/proposed_supersedes 제안에 참고) ===\n"
        + _decisions_index(root)
        + "\n\n=== git 히스토리 슬라이스 ===\n"
        + body
    )
    text = BACKENDS[backend](prompt)
    drafts = _split_drafts(text)

    pending = os.path.join(root, ".claude/memory/_pending/decisions")
    written = []
    for d in drafts:
        if not _is_decision(d):
            continue  # 마이닝은 ADR 만 — 비-decision 초안은 버린다
        os.makedirs(pending, exist_ok=True)
        slug = _slug(d)
        path = os.path.join(pending, f"{slug}.md")
        # 같은 slug 가 이미 대기 중이면 덮지 않고 suffix 로 보존(reflect 와 동일 — /memory-update 가 병합).
        i = 2
        while os.path.exists(path):
            path = os.path.join(pending, f"{slug}-{i}.md")
            i += 1
        open(path, "w", encoding="utf-8").write(d + "\n")
        written.append(os.path.basename(path))
    sys.stderr.write(
        f"[mine] backend={backend} {rev_range} 커밋 {n}개 → ADR 초안 {len(written)}개"
        f"{': ' + ', '.join(written) if written else ' (왜가 안 적힌 슬라이스면 정상)'}\n"
    )


if __name__ == "__main__":
    main()
