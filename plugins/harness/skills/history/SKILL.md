---
name: history
description: Claude·Codex 로컬 세션 로그를 시간순으로 조회·검색하고 선택한 로그의 fw 이어받기 명령을 출력
context: fork
allowed-tools: Bash, Read
argument-hint: "선택: --from / --limit / --since / --grep / --no-content"
---

# history

`history`는 세션을 복원하지 않는 **읽기 전용 탐색 단계**다. 어느 세션을 이어받을지 찾고,
실제 복원은 출력된 `fw --session` 명령에 맡긴다.

## 실행

```bash
agent-handoff history --from both --limit 20 --since 30d
agent-handoff history --grep "useStudyProgress" --since 7d
agent-handoff history --no-content
```


출력:
- 갱신 시각과 툴(Claude/Codex)
- 로그 전체 경로
- 프로젝트 매치 방식
- 마지막 사용자 입력 snippet
- 선택한 로그를 이어받는 복붙 가능한 `fw --session <경로>` 명령

## 옵션과 경계

- `--from claude|codex|both` (기본 both)
- `--limit N` (기본 20)
- `--since 30m|12h|7d|2w` (기본 30d)
- `--grep <키워드>` — 최근 기간의 최신 후보 최대 200개(파일 개수 기준) 안에서 JSONL 전체를 대소문자 무시 검색
- `--no-content` — 프롬프트를 터미널에 표시하지 않고 경로·메타데이터만 조회
- `--json` — 자동화용

로그 형식은 툴 버전에 따라 바뀔 수 있어 best-effort로 파싱한다. 파싱할 수 없는 snippet은
비워 두되 목록 전체를 실패시키지 않는다. Claude는 프로젝트 디렉터리 키, Codex는 rollout의
`cwd`로 프로젝트를 판별하므로 오탐·누락 가능성이 있다.

Codex rollout은 시작 날짜 디렉터리가 오래됐어도 최근 resume로 파일 mtime이 바뀔 수 있어,
날짜 폴더가 아니라 전체 세션 트리의 mtime을 먼저 확인한 뒤 `--since`를 적용한다.

`history`는 목록·검색·경로 출력까지만 한다. 자동 복원하거나 로그를 수정하지 않는다.
