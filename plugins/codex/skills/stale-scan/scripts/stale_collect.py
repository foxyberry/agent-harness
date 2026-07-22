#!/usr/bin/env python3
"""
stale issue detector — A 조각: open 이슈 수집 + 정책 라벨 필터.

무엇: 한 repo 의 open 이슈를 조회하고, 정책 라벨(keep·blocked·needs-repro·
tracking·epic·good first issue 등)을 가진 것을 "검토 대상"에서 제외한 뒤,
나이 정보와 함께 JSON 으로 출력한다.

왜: stale 판정 대상 집합을 먼저 정확히 좁혀야 오탐이 준다. 메타/트래킹 이슈는
연결된 merged PR 이 여러 개여도 닫으면 안 되므로, 애초에 후보에서 뺀다.

⚠️ 나이(age_days·updated_days)는 **정렬용 신호**일 뿐이다. close 판정 신호가
아니다(오래됐어도 유효할 수 있다 — stale ≠ resolved). `--min-age-days` 는 수집
범위를 좁히는 선택적 필터지, "닫아라"라는 뜻이 아니다.

이 스크립트는 stale detector 의 B(연결 PR 리졸버 = stale_resolve.py)·
C(판정 리포트 = stale.py)와 독립이다. 설계·계약 정본:
docs/stale-issue-detector.md 의 "데이터 계약" 섹션.

출력 (JSON array → stdout):
  [{"issue": 41, "title": "...", "labels": ["bug"],
    "age_days": 120, "updated_days": 30, "url": "https://..."}]
나이 내림차순(오래된 것 먼저) 정렬.

stdlib 전용 + gh CLI. Python 3.8+.

사용:
  python3 stale_collect.py --repo owner/name
  python3 stale_collect.py --repo owner/name --min-age-days 30
  python3 stale_collect.py --repo owner/name --exclude-label wontfix --exclude-label keep
"""
import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone

# 기본 제외 라벨 — 후보에서 뺀다(설계: docs/stale-issue-detector.md).
# 메타/트래킹/보류/유지 성격이라 연결 PR 유무와 무관하게 닫으면 안 되는 것들.
DEFAULT_EXCLUDE_LABELS = [
    "keep",
    "blocked",
    "needs-repro",
    "tracking",
    "epic",
    "good first issue",
]


def _fail(msg, code=1):
    print(f"stale_collect: {msg}", file=sys.stderr)
    sys.exit(code)


def _parse_iso(ts):
    """GitHub ISO8601 (…Z) → aware datetime. 파싱 실패 시 None."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def fetch_open_issues(repo, limit):
    """gh issue list 로 open 이슈를 가져온다. gh 없음/인증실패는 명확히 종료.

    ⚠️ `sort:created-asc` 로 **오래된 이슈부터** 받는다. --limit 로 잘릴 때
    newest(가장 안 오래된) 쪽이 버려지도록 — stale 탐지는 오래된 이슈가 대상이라
    gh 기본 정렬(created desc)이면 정작 필요한 걸 놓친다.
    """
    try:
        proc = subprocess.run(
            [
                "gh", "issue", "list",
                "--repo", repo,
                "--state", "open",
                "--search", "sort:created-asc",
                "--limit", str(limit),
                "--json", "number,title,labels,createdAt,updatedAt,url",
            ],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        _fail("gh CLI 를 찾을 수 없습니다. GitHub CLI 를 설치하세요.")
    if proc.returncode != 0:
        _fail(f"gh issue list 실패 (repo={repo}):\n{proc.stderr.strip()}")
    try:
        return json.loads(proc.stdout or "[]")
    except json.JSONDecodeError as e:
        _fail(f"gh 출력 파싱 실패: {e}")


def _row(it, now):
    """gh 이슈 dict → 우리 출력 row (라벨·나이 계산)."""
    names = [lbl.get("name", "") for lbl in it.get("labels", [])]
    created = _parse_iso(it.get("createdAt"))
    updated = _parse_iso(it.get("updatedAt"))
    return {
        "issue": it.get("number"),
        "title": it.get("title", ""),
        "labels": names,
        "age_days": (now - created).days if created else None,
        "updated_days": (now - updated).days if updated else None,
        "url": it.get("url", ""),
    }


def _sort_oldest_first(rows):
    # 나이 내림차순(오래된 것 먼저). age 미상은 맨 뒤로.
    rows.sort(key=lambda r: (r["age_days"] is None, -(r["age_days"] or 0)))
    return rows


def partition(repo, min_age_days, exclude_labels, limit, now=None):
    """open 이슈를 (검토대상 후보, 정책 제외) 로 나눠 반환한다.

    C(리포트)가 '제외 라벨 별도 표시'를 하려면 제외된 이슈도 알아야 하므로,
    한 번의 fetch 로 둘 다 돌려준다. 둘 다 나이 내림차순.
    """
    now = now or datetime.now(timezone.utc)
    excl = {lbl.strip().lower() for lbl in exclude_labels}  # 대소문자 무시 정확 일치
    candidates, excluded = [], []
    for it in fetch_open_issues(repo, limit):
        row = _row(it, now)
        # 나이 범위 필터는 분기 전에 **공통** 적용한다 — --min-age-days 는 스캔 "범위"라
        # 후보든 정책제외든 같은 범위를 봐야 리포트가 일관된다(정렬/판정 신호 아님).
        if min_age_days is not None and (row["age_days"] is None or row["age_days"] < min_age_days):
            continue
        if any(n.strip().lower() in excl for n in row["labels"]):
            excluded.append(row)  # 정책 라벨 → 후보에서 제외(하지만 별도 보존)
            continue
        candidates.append(row)
    return _sort_oldest_first(candidates), _sort_oldest_first(excluded)


def collect(repo, min_age_days, exclude_labels, limit, now=None):
    """검토 대상 후보만 반환(A 의 CLI 계약)."""
    candidates, _ = partition(repo, min_age_days, exclude_labels, limit, now)
    return candidates


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="open 이슈 수집 + 정책 라벨 필터 (stale detector A 조각)"
    )
    ap.add_argument("--repo", required=True, help="owner/name")
    ap.add_argument(
        "--min-age-days", type=int, default=None,
        help="이 일수보다 오래된 이슈만 수집(선택, 수집 범위 축소용 — 판정 신호 아님)",
    )
    ap.add_argument(
        "--exclude-label", action="append", dest="exclude_labels", default=None,
        help=f"제외할 라벨을 **추가**(반복 가능). 기본 제외 라벨({', '.join(DEFAULT_EXCLUDE_LABELS)})에 더해진다.",
    )
    ap.add_argument(
        "--no-default-excludes", action="store_true",
        help="기본 제외 라벨을 쓰지 않는다(완전 커스텀 — --exclude-label 로 준 것만 제외).",
    )
    ap.add_argument(
        "--limit", type=int, default=500,
        help="gh issue list 최대 조회 수(기본 500, oldest-first 라 초과분은 newest 쪽이 잘림)",
    )
    args = ap.parse_args(argv)

    # 기본 제외 라벨은 항상 적용하고, --exclude-label 은 거기에 **더한다**(union).
    # 정책 라벨(keep·blocked 등)이 실수로 빠져 오탐 후보가 되는 걸 막는다.
    # 완전 커스텀이 필요하면 --no-default-excludes 로 기본값을 끈다.
    exclude_labels = set() if args.no_default_excludes else set(DEFAULT_EXCLUDE_LABELS)
    exclude_labels |= set(args.exclude_labels or [])
    rows = collect(args.repo, args.min_age_days, exclude_labels, args.limit)
    print(json.dumps(rows, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
