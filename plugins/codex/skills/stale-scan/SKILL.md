---
name: stale-scan
description: 오래된 open 이슈 중 '이미 해결된(닫아도 될) 후보'를 연결된 merged PR 근거로 찾아 advisory 리포트. 자동 close 안 함. 이슈 백로그 정리할 때 사용
context: fork
allowed-tools: Bash, Read
argument-hint: "--repo owner/name (필수) / --min-age-days N / --exclude-label L / --json"
---

# stale 이슈 스캔 (stale-scan)

오래된 open GitHub 이슈 중 **이미 해결됐을(닫아도 될) 후보**를 찾아 리포트한다. 판단 근거는
**GitHub 이 연결한 '닫는 merged PR'** 뿐이다(고정밀). **자동으로 닫지 않는다** — advisory 다.
리포트를 사람이 보고 판단한다.

## 언제 쓰나

- "오래된 이슈 정리하자", "닫아도 될 이슈 찾아줘", "stale 이슈 스캔"
- 이슈 백로그가 쌓여 이미 해결된 게 섞여 있을 때

## 실행

```
python3 scripts/stale.py --repo <owner/name>
```
> ⚠️ 위 `scripts/stale.py` 는 이 SKILL.md 가 있는 스킬 디렉토리 기준 상대경로다. 그 스킬 폴더로 cd 한 뒤 실행하라. (`--repo` 로 대상 repo 를 명시하므로 cwd/git 루트에는 의존하지 않지만, 명령의 `scripts/` 경로 때문에 스킬 폴더에서 실행해야 한다.)
옵션:
- `--min-age-days N` — N일보다 오래된 이슈만 검토(범위 축소용)
- `--exclude-label L` — 제외할 정책 라벨 **추가**(반복). 기본 제외: `keep·blocked·needs-repro·tracking·epic·good first issue`
- `--no-default-excludes` — 기본 제외 라벨 끄기(완전 커스텀)
- `--json` — 사람용 리포트 대신 기계용 JSON

## 리포트 읽는 법

- **닫기후보** — 그 이슈를 cross-reference 하는 **merged PR 이 존재**한다. 근거 PR 링크가 붙는다.
  사람이 그 링크를 열어 정말 해결됐는지 확인하고 닫을지 판단한다.
- **유지 / 불확실** — 연결된 merged PR 이 없다. **닫지 않는다.**
- **정책 제외** — `keep·epic` 같은 정책 라벨을 단 이슈. 판정하지 않는다(메타/트래킹 이슈는
  PR 이 여럿 걸려도 닫으면 안 되므로 애초에 뺀다).

## 한계 (MVP)

- **cross-reference ≠ 해결**: PR 이 이슈를 언급(cross-ref)만 하고 실제 해결은 안 했을 수 있다.
  그래서 한 후보에 PR 이 여러 개 붙어 나올 수 있다 — **반드시 링크를 열어 확인**하고 사람이 판단한다.
- `rg` 코드 흔적·LLM 의미 매칭·자동 close 는 범위 밖(v2). 나이는 정렬/범위축소에만 쓴다(판정 신호 아님).

## 하지 않는 것

- **자동 close 금지.** 이 스킬은 리포트만 낸다. 닫기는 사람이 별도로 한다.
- SessionStart 등 자동 훅으로 상시 돌리지 않는다 — 명시 실행만(gh 비용·rate limit·auth 실패가
  사용자 흐름을 방해하지 않도록).
