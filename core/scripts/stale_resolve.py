#!/usr/bin/env python3
"""
GitHub issue 에 연결된 merged Pull Request 를 해석한다.

stale issue detector 의 B 조각: open issue 가 자동으로 닫히지 않았더라도
timeline 의 cross-reference/connection/closed 이벤트에 merged PR 이 있으면
"해결 신호"로 본다.

stdlib + gh CLI 전용. JSON object 를 stdout 으로 출력한다.

사용:
  python3 core/scripts/stale_resolve.py --repo owner/name --issues 41,42,43
"""
import argparse
import json
import subprocess
import sys

CHUNK_SIZE = 20
PAGE_SIZE = 100
TIMELINE_TYPES = "CROSS_REFERENCED_EVENT, CONNECTED_EVENT, CLOSED_EVENT"


def die(message):
    print(f"error: {message}", file=sys.stderr)
    return 1


def parse_repo(value):
    parts = value.split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise argparse.ArgumentTypeError("repo 는 owner/name 형식이어야 합니다")
    return parts[0], parts[1]


def parse_issues(value):
    issues = []
    seen = set()
    for raw in value.split(","):
        item = raw.strip()
        if not item:
            continue
        try:
            number = int(item, 10)
        except ValueError:
            raise argparse.ArgumentTypeError(
                f"issue 번호가 정수가 아닙니다: {item}"
            )
        if number <= 0:
            raise argparse.ArgumentTypeError(
                f"issue 번호는 양수여야 합니다: {item}"
            )
        if number not in seen:
            issues.append(number)
            seen.add(number)
    if not issues:
        raise argparse.ArgumentTypeError("하나 이상의 issue 번호가 필요합니다")
    return issues


def chunks(items, size):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def pr_fields_fragment():
    return """
fragment PrFields on PullRequest {
  number
  url
  merged
  mergedAt
  state
}
"""


def issue_field(number):
    alias = issue_alias(number)
    after_var = after_var_name(number)
    return f"""
    {alias}: issue(number: {number}) {{
      timelineItems(
        first: {PAGE_SIZE}
        after: ${after_var}
        itemTypes: [{TIMELINE_TYPES}]
      ) {{
        pageInfo {{
          hasNextPage
          endCursor
        }}
        nodes {{
          __typename
          ... on CrossReferencedEvent {{
            willCloseTarget
            source {{
              __typename
              ...PrFields
            }}
          }}
          ... on ConnectedEvent {{
            subject {{
              __typename
              ...PrFields
            }}
          }}
          ... on ClosedEvent {{
            closer {{
              __typename
              ...PrFields
            }}
          }}
        }}
      }}
    }}
"""


def build_query(issue_numbers):
    after_decls = " ".join(
        f"${after_var_name(n)}: String" for n in issue_numbers
    )
    declarations = f"$owner: String! $name: String! {after_decls}".strip()
    fields = "".join(issue_field(n) for n in issue_numbers)
    return f"""
query({declarations}) {{
  repository(owner: $owner, name: $name) {{
{fields}
  }}
}}
{pr_fields_fragment()}
"""


def issue_alias(number):
    return f"i{number}"


def after_var_name(number):
    return f"after_i{number}"


def run_graphql(owner, name, issue_numbers, cursors):
    cmd = [
        "gh", "api", "graphql",
        "-f", f"query={build_query(issue_numbers)}",
        "-f", f"owner={owner}",
        "-f", f"name={name}",
    ]
    for number in issue_numbers:
        cursor = cursors.get(number)
        if cursor:
            cmd.extend(["-f", f"{after_var_name(number)}={cursor}"])

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except FileNotFoundError:
        raise RuntimeError("gh CLI 를 찾을 수 없습니다. GitHub CLI 설치가 필요합니다.")
    except subprocess.TimeoutExpired:
        raise RuntimeError("gh api graphql 호출이 60초 안에 끝나지 않았습니다.")

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        if not detail:
            detail = f"exit code {proc.returncode}"
        raise RuntimeError(f"gh api graphql 실패: {detail}")

    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"gh api graphql 응답이 JSON 이 아닙니다: {exc}")

    if payload.get("errors"):
        raise RuntimeError(
            "GitHub GraphQL 오류: "
            + json.dumps(payload["errors"], ensure_ascii=False)
        )
    return payload


def pull_request_from_node(node):
    typename = node.get("__typename")
    if typename == "CrossReferencedEvent":
        return node.get("source")
    if typename == "ConnectedEvent":
        return node.get("subject")
    if typename == "ClosedEvent":
        return node.get("closer")
    return None


def add_merged_prs(result, issue_number, nodes):
    by_pr = {item["pr"]: item for item in result[str(issue_number)]}
    for node in nodes or []:
        if not isinstance(node, dict):
            continue
        pr = pull_request_from_node(node) or {}
        if pr.get("__typename") != "PullRequest":
            continue
        if pr.get("merged") is not True:
            continue
        number = pr.get("number")
        if not isinstance(number, int):
            continue
        by_pr[number] = {
            "pr": number,
            "url": pr.get("url"),
            "merged_at": pr.get("mergedAt"),
        }
    result[str(issue_number)] = [by_pr[n] for n in sorted(by_pr)]


def resolve(owner, name, issues):
    result = {str(number): [] for number in issues}

    for chunk in chunks(issues, CHUNK_SIZE):
        cursors = {}
        active = list(chunk)
        while active:
            payload = run_graphql(owner, name, active, cursors)
            repo = (payload.get("data") or {}).get("repository") or {}
            next_active = []
            for number in active:
                issue = repo.get(issue_alias(number))
                if issue is None:
                    raise RuntimeError(
                        f"issue #{number} 조회 결과가 없습니다. repo/권한을 확인하세요."
                    )
                timeline = issue.get("timelineItems") or {}
                add_merged_prs(
                    result,
                    number,
                    timeline.get("nodes") or [],
                )
                page_info = timeline.get("pageInfo") or {}
                if page_info.get("hasNextPage") and page_info.get("endCursor"):
                    cursors[number] = page_info["endCursor"]
                    next_active.append(number)
            active = next_active

    return result


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Issue timeline 에서 연결된 merged PR 을 JSON 으로 출력합니다."
    )
    parser.add_argument("--repo", required=True, type=parse_repo,
                        help="GitHub repository, owner/name")
    parser.add_argument("--issues", required=True, type=parse_issues,
                        help="쉼표로 구분한 issue 번호 목록")
    args = parser.parse_args(argv)

    owner, name = args.repo
    try:
        data = resolve(owner, name, args.issues)
    except RuntimeError as exc:
        return die(str(exc))

    json.dump(data, sys.stdout, ensure_ascii=False, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
