#!/usr/bin/env python3
"""
stale issue detector — C 조각: 판정 + advisory 리포트 (orchestrator).

A(stale_collect: 검토 대상 후보 + 정책 제외)와 B(stale_resolve: 연결된 닫는
merged PR)를 합쳐, 이슈별 판정과 근거 링크를 담은 리포트를 낸다.

판정(결정론):
  - 연결된 merged PR 이 있으면 → **닫기후보** (근거 PR 링크 첨부)
  - 없으면 → **유지 / 불확실** (닫지 않음)
  - 정책 라벨(keep·blocked·epic 등) 이슈는 → **정책 제외** 로 별도 표시(판정 안 함)

⚠️ 이 도구는 **advisory** 다. 이슈를 자동으로 닫지 않는다. 사람이 리포트를 보고
판단한다. (설계: docs/stale-issue-detector.md — 자동 close 금지, 명시 실행만.)

A·B 스크립트를 같은 폴더에서 import 한다(co-located). 이 스크립트는 --repo 를
명시로 받으므로 cwd/git-루트에 의존하지 않는다.

stdlib 전용 + gh CLI (A·B 를 통해). Python 3.8+.

사용:
  python3 stale.py --repo owner/name
  python3 stale.py --repo owner/name --min-age-days 30
  python3 stale.py --repo owner/name --json
"""
import argparse
import json
import os
import sys

# A·B 를 같은 디렉토리에서 import (번들 시 co-located).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stale_collect import partition, DEFAULT_EXCLUDE_LABELS  # noqa: E402
from stale_resolve import resolve  # noqa: E402


def _split_repo(repo):
    parts = repo.split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        print("stale: --repo 는 owner/name 형식이어야 합니다", file=sys.stderr)
        sys.exit(2)
    return parts[0], parts[1]


def judge(repo, min_age_days, exclude_labels, limit):
    """A·B 를 돌려 판정 결과를 만든다. 반환:
    {"repo","closable":[...],"keep":[...],"excluded":[...]}
    각 후보 row 에 'linked_prs' 를 붙인다.
    """
    owner, name = _split_repo(repo)
    candidates, excluded = partition(repo, min_age_days, exclude_labels, limit)

    numbers = [c["issue"] for c in candidates if isinstance(c.get("issue"), int)]
    linked = resolve(owner, name, numbers) if numbers else {}

    closable, keep = [], []
    for c in candidates:
        prs = linked.get(str(c["issue"]), [])
        row = dict(c, linked_prs=prs)
        (closable if prs else keep).append(row)

    return {"repo": repo, "closable": closable, "keep": keep, "excluded": excluded}


def _age(row):
    d = row.get("age_days")
    return f"{d}d" if d is not None else "?"


def render_text(result):
    repo = result["repo"]
    closable, keep, excluded = result["closable"], result["keep"], result["excluded"]
    lines = []
    lines.append(f"stale issue 리포트 — {repo}")
    lines.append(
        f"검토 {len(closable) + len(keep)}건 · 정책제외 {len(excluded)}건  "
        f"| 닫기후보 {len(closable)} · 유지 {len(keep)}"
    )
    lines.append(
        "판정: 연결된 merged PR 이 있으면 '닫기후보', 없으면 '유지/불확실'. "
        "자동 close 안 함 — 사람이 판단."
    )
    lines.append("")

    lines.append(f"■ 닫기후보 ({len(closable)})  ← 연결된 merged PR 존재")
    if not closable:
        lines.append("  (없음)")
    for r in closable:
        lines.append(f"  #{r['issue']}  (age {_age(r)})  {r['title']}")
        for pr in r["linked_prs"]:
            merged = (pr.get("merged_at") or "")[:10]
            lines.append(f"       └ PR #{pr['pr']} merged {merged}  {pr.get('url','')}")
    lines.append("")

    lines.append(f"■ 유지 / 불확실 ({len(keep)})  ← 연결된 merged PR 없음")
    if not keep:
        lines.append("  (없음)")
    for r in keep:
        lines.append(f"  #{r['issue']}  (age {_age(r)})  {r['title']}  {r['url']}")
    lines.append("")

    lines.append(f"■ 정책 제외 ({len(excluded)})  ← 정책 라벨, 판정 안 함")
    if not excluded:
        lines.append("  (없음)")
    for r in excluded:
        labels = ", ".join(r["labels"])
        lines.append(f"  #{r['issue']}  [{labels}]  {r['title']}")

    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="판정 + advisory 리포트 (stale detector C 조각). 자동 close 안 함."
    )
    ap.add_argument("--repo", required=True, help="owner/name")
    ap.add_argument("--min-age-days", type=int, default=None,
                    help="이 일수보다 오래된 이슈만 검토(선택, 범위 축소용)")
    ap.add_argument("--exclude-label", action="append", dest="exclude_labels", default=None,
                    help=f"제외할 라벨을 추가(반복). 기본: {', '.join(DEFAULT_EXCLUDE_LABELS)}")
    ap.add_argument("--no-default-excludes", action="store_true",
                    help="기본 제외 라벨을 쓰지 않는다.")
    ap.add_argument("--limit", type=int, default=500,
                    help="gh issue list 최대 조회 수(기본 500, oldest-first)")
    ap.add_argument("--json", action="store_true", help="사람용 리포트 대신 JSON 출력")
    args = ap.parse_args(argv)

    exclude_labels = set() if args.no_default_excludes else set(DEFAULT_EXCLUDE_LABELS)
    exclude_labels |= set(args.exclude_labels or [])

    result = judge(args.repo, args.min_age_days, exclude_labels, args.limit)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(render_text(result))


if __name__ == "__main__":
    main()
