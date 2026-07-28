# 자기개선 훅 (Self-improvement hooks)

이 하네스의 차별점은 스킬 위의 **자기개선 루프**다. 작업이 진행되는 동안 관련 지식을
자동으로 꺼내 보여주고(주입), 방금 쓴 코드에 대해 경고하고(회고), 머지될 때 교훈을
남겨(반영) 다음 세션이 더 잘하게 만든다.

```
project-memory-index  ──▶  memory-search  ──▶  reflection  ──▶  pr-merge-reflect  ──▶  /memory-update
(세션 시작 인덱스)        (편집 전 주입)      (편집 후 경고)      (머지 시 회고)         (승격·영속화)
```

훅은 **Claude 어댑터에만** 배포된다(`plugins/harness/hooks/`). Codex 훅은 버전 취약
(openai/codex#19385·#21639)으로 defer — 스킬(`/feedback-review`, `/memory-update`)은 양쪽 배포된다.

---

## 설계 원칙: 엔진(core) ↔ 데이터(프로젝트)

훅 스크립트는 **툴·프로젝트 무관 generic 엔진**이다. "무엇을" 주입·경고할지는
core 에 하드코딩하지 않고, **프로젝트의 `.claude/memory/` 데이터 파일**이 정한다.

| | 엔진 (core) | 데이터 (프로젝트) |
|---|---|---|
| project-memory-index | INDEX.md 읽기 → 공유 메모리 목록 주입 | `INDEX.md`, 선택: `index-load.json` |
| memory-search | glob/substring 매칭 → 메모리 주입 | `routes.json` (파일→메모리 매핑) |
| reflection | 정규식 규칙 적용 → 경고 | `reflection-rules.json` (패턴→경고문) |

데이터 파일이 없으면 훅은 **조용히 no-op** 한다(reflection 은 내장 TODO/FIXME 규칙만).
예시 데이터는 `project-template/.claude/memory/` 에 있다(Kotlin/Spring 기준 — 네 프로젝트에 맞게 고쳐라).

### 경로 규약 (중요)

플러그인에선 **스크립트 위치와 데이터 위치가 갈린다**:

- **스크립트** → `${CLAUDE_PLUGIN_ROOT}/hooks/` (플러그인 설치 위치). 훅끼리 co-locate 돼
  `pr-merge-reflect` 가 `reflect.py` 를, `reflect.py` 가 `compact_transcript.py` 를 `dirname(__file__)` 로 찾는다.
- **데이터** → `$CLAUDE_PROJECT_DIR/.claude/memory/` (프로젝트 루트). routes/rules/메모리/`_pending`/캐시 전부 여기.

---

## 훅별 상세

### project-memory-index — 세션 시작 시 공유 메모리 목록 주입
- **이벤트**: SessionStart
- **동작**: `.claude/memory/INDEX.md` 를 읽어 `additionalContext` 로 주입한다. 목적은 메모리 본문 전체를
  자동으로 넣는 것이 아니라, 어떤 공유 규칙·결정·회고가 있는지 세션 초반에 발견하게 하는 것이다.
  실제 상세 파일은 현재 작업에 관련될 때 읽는다.
- **크기 제한**: 기본 12,000자까지만 주입하고 넘치면 잘림 표시를 붙인다.
- **옵션**: `.claude/memory/index-load.json` 으로 끄거나 크기 제한을 조정할 수 있다.

`index-load.json` 형식:
```json
{
  "enabled": true,
  "max_chars": 12000
}
```
- `enabled: false` 면 INDEX 자동 주입을 끈다.
- `max_chars` 는 1,000~50,000 사이로 clamp 된다.

### memory-search — 편집 전 관련 메모리 주입
- **이벤트**: PreToolUse `Edit|Write|MultiEdit`
- **동작**: 편집하려는 파일 경로를 `routes.json` 규칙과 매칭 → 매칭된 메모리 파일을 읽어
  `additionalContext` 로 컨텍스트에 주입. "이 파일 고칠 땐 이 규칙·결정을 기억하라."
- **보안**: routes.json 은 프로젝트 제어 데이터라, 경로 탈출(절대경로·`..`·symlink)로 `.claude/memory`
  밖 파일을 주입하려는 시도를 차단한다(untrusted repo 유출 방지).

`routes.json` 형식:
```json
{
  "rules": [
    { "glob": "*.kt", "memory": ["patterns/code-quality.md"] },
    { "contains": ["batch", "etl"], "memory": ["decisions/issue-workflow.md"] },
    { "contains": ["git"], "match_empty": true, "memory": ["decisions/git-workflow.md"] }
  ]
}
```
- `glob`: 파일 경로에 fnmatch. `contains`: 부분문자열(대소문자 무시) 중 하나라도 포함.
- `match_empty`: 경로 없는 편집도 매칭. `memory`: `.claude/memory/` 기준 상대경로.

### reflection — 편집 후 품질 경고
- **이벤트**: PostToolUse `Edit|Write|MultiEdit` (MultiEdit 은 `edits[*].new_string` 을 합쳐 검사)
- **동작**: 방금 쓴 코드에 `reflection-rules.json` 정규식 규칙을 적용 → 경고를 tool result 옆에 주입.
- **내장 규칙**: TODO/FIXME 잔존 경고(모든 파일, 언어 무관). 끄려면 `"builtins": {"todo_fixme": false}`.

`reflection-rules.json` 형식:
```json
{
  "rules": [
    { "glob": "*.kt", "regex": "!!",
      "message": "`!!` 사용 {count}곳 — requireNotNull 또는 ?: return 검토" },
    { "glob": "*.kt", "regex": "(?m)^\\s*var ", "min_count": 3,
      "message": "var 선언 다수({count}) — fold/associate/sumOf 검토" }
  ]
}
```

규칙 묶음은 `packs` 로 opt-in 할 수 있다. 엔진은 pack 내용을 모르고, `enabled: true` 인
pack의 `rules`를 일반 규칙 뒤에 붙여 실행한다:

```json
{
  "rules": [],
  "packs": [
    {
      "name": "react-async-timing",
      "enabled": true,
      "rules": [
        {"globs": ["*.js", "*.jsx", "*.ts", "*.tsx"],
         "regex": "...", "message": "..."}
      ]
    }
  ]
}
```

`project-template`의 `react-async-timing` 스타터 팩은 기본 꺼짐이다. React 프로젝트에서
`enabled`를 `true`로 바꾸면 state updater 안 부수효과, catch 완료 신호 누락 후보,
렌더 중 `ref.current` 분기, effect 첫 동작의 컬렉션 초기화를 경고한다. 정규식은 AST나
실행 순서를 확정하지 못하므로 경고를 버그 판정으로 취급하지 않는다. 실제 scope를 확인하고
`renderHook` + `rerender`로 pending/reject, 계정 전환, unmount/remount 순서를 재현한다.
- `glob`: 적용 파일. `globs`: 여러 파일 패턴 배열(둘 다 생략 시 전체). 지정한 값이
  문자열/문자열 배열이 아니거나 배열이 비어 있으면 범위를 넓히지 않고 해당 규칙을 건너뛴다.
- `regex`: Python re 패턴. `enabled: false`: 해당 규칙만 비활성.
- `min_count`: 이 수 이상일 때만(기본 1).
- `message`: `{count}` 는 매칭 수로 치환.

PostToolUse의 `Edit`는 파일 전체가 아니라 교체된 `new_string` 조각만 검사한다. 여러 줄 구조가
조각 밖에 걸쳐 있으면 경고를 놓치거나 문맥 부족으로 후보를 넓게 잡을 수 있다. `Write`는 파일
전체를 검사하지만, 두 경우 모두 경고는 확인을 위한 신호이며 정적 분석 결과가 아니다. 스타터
팩의 bounded regex는 중첩 블록을 따라가지 않으므로 경고가 없다고 안전이 보장되는 것도 아니다.

### pr-merge-reflect — 머지 회고 루프 (핵심)
- **이벤트**: PostToolUse `Bash`, SessionStart, UserPromptSubmit
- **두 역할**:

  **A) 리마인더 (항상 켜짐, LLM 안 씀)** — 머지됐는데 회고 안 한 PR 을 큐에 쌓고, 다음 발화 때
  "회고부터 하라(`/feedback-review`·`/memory-update`)" 지시를 주입한다. 감지 경로:
  - SessionStart 폴링(외부 머지 포함) · PostToolUse(`gh pr merge` — **실제 MERGED 확인 후에만**) ·
    UserPromptSubmit("머지했어" 발화)

  **B) 자동 회고 잡 (opt-in, 기본 꺼짐)** — 아래 참조.

#### 회고 skip rule

회고를 저장하기 위한 PR 이 다시 "회고하라"는 리마인더를 만드는 루프를 막기 위해,
`pr-merge-reflect` 는 회고 산출물만 변경한 PR 을 pending/자동 회고 대상에서 제외한다.

기본 skip:
- 변경 파일이 전부 `.claude/memory/**`
- 변경 파일이 전부 `.claude/handoff/**`
- 변경 파일이 전부 `.agents/skills/**`
- PR 라벨이 `skip-reflect` 또는 `no-reflect`
- 커밋 메시지에 `[skip reflect]`, `skip-reflect`, `no-reflect` 포함

프로젝트별로 `.claude/memory/reflect-skip.json` 에서 패턴을 확장할 수 있다.

```json
{
  "paths": [".claude/memory/**", ".claude/handoff/**", ".agents/skills/**"],
  "labels": ["skip-reflect", "no-reflect"],
  "commit_messages": ["[skip reflect]", "skip-reflect", "no-reflect"]
}
```

- `paths`: PR 변경 파일이 **전부** 이 패턴들에 매칭될 때 skip 한다(fnmatch).
- `labels`: PR 라벨이 하나라도 매칭되면 skip 한다(fnmatch, 대소문자 무시).
- `commit_messages`: 커밋 메시지에 문자열이 하나라도 포함되면 skip 한다(대소문자 무시).
- `"defaults": false` 를 두면 내장 기본값을 비우고 프로젝트 설정만 사용한다.

### reflect.py + compact_transcript.py — 자동 회고 잡
`pr-merge-reflect` 가 스폰하는 백그라운드 잡. 세션 트랜스크립트(Claude `.jsonl` / Codex rollout 둘 다)를
압축 → LLM 으로 분석 → 영속할 교훈을 `.claude/memory/_pending/*.md` 에 **초안**으로 저장.
detached 라 세션을 닫아도 완료된다. 같은 slug 초안은 덮어쓰지 않고 suffix 로 보존한다.

---

## ⚠️ 자동 회고는 opt-in (기본 꺼짐)

자동 회고 잡은 `claude -p`(또는 deepseek/ollama) **백그라운드 LLM 프로세스**를 띄운다.
플러그인 설치만으로 모든 프로젝트의 머지마다 조용히 LLM 잡이 뜨는 걸 막기 위해, **기본 꺼짐**이다.

```bash
export HARNESS_AUTO_REFLECT=1          # 켜기 — 머지 시 회고 초안 자동 생성
export REFLECT_BACKEND=claude          # claude(기본) | deepseek | ollama
```
켜도 **리마인더(역할 A)는 무관하게 항상 동작**한다. 끄면 회고를 사람이 직접 `/memory-update` 로 하면 된다.

`_pending/` 초안은 `/memory-update` 로 검토 → **승격 / 병합 / 폐기**. governance:
초안은 자동으로 메모리에 박히지 않고 사람 승인을 거친다(`_pending → 승인 → committed`).

---

## 설정 요약

| 무엇 | 어디 | 없으면 |
|------|------|--------|
| 공유 메모리 인덱스 | `$CLAUDE_PROJECT_DIR/.claude/memory/INDEX.md` | project-memory-index no-op |
| INDEX 자동 주입 옵션 | `$CLAUDE_PROJECT_DIR/.claude/memory/index-load.json` | enabled=true, max_chars=12000 |
| 파일→메모리 매핑 | `$CLAUDE_PROJECT_DIR/.claude/memory/routes.json` | memory-search no-op |
| 코드 품질 규칙 | `$CLAUDE_PROJECT_DIR/.claude/memory/reflection-rules.json` | 내장 TODO/FIXME 만 |
| 회고 skip rule | `$CLAUDE_PROJECT_DIR/.claude/memory/reflect-skip.json` | 기본 회고 산출물 경로·라벨·커밋 메시지 skip |
| 자동 회고 on | env `HARNESS_AUTO_REFLECT=1` | 리마인더만(회고 수동) |
| 회고 백엔드 | env `REFLECT_BACKEND` | `claude` |

전부 fail-open — `.claude/memory/` 가 없는 프로젝트에서도 훅은 조용히 통과하며 세션을 막지 않는다.

---

## 알려진 한계 (auto-reflect 켤 때만)

자동 회고(`HARNESS_AUTO_REFLECT=1`)를 켰을 때만 해당되는 두 한계가 있다. 기본 off 라 일상 사용엔 영향 없다.

- **회고 잡은 "스폰 성공 = seen" 으로 처리한다.** `reflect.py` 는 detached 로 뜨고, 그 안의
  `claude -p`(또는 API 백엔드)가 스폰 후 실패(PATH 없음·타임아웃·비정상 종료)하면 초안이 0개여도
  그 세션은 이미 seen 이라 **다음 스윕에서 재시도되지 않는다** → 그 머지/세션 회고가 유실될 수 있다.
  실패는 `.claude/.cache/reflect.log` 에 남는다. (완료-확인 후 seen 처리 = 상태 콜백은 후속 과제.)
- **초안 파서는 중첩 코드펜스에서 잘릴 수 있다.** `reflect.py` 의 `_split_drafts` 는 non-greedy
  ` ``` ` 펜스 매칭이라, LLM 초안 본문에 ` ``` ` 예시 블록이 들어가면 그 지점에서 잘려 저장될 수 있다.
  → `/memory-update` 검토 시 잘린 초안은 폐기·재작성한다.

## 검증 상태

- **구현 + 스모크테스트 완료** — 각 훅의 no-op·매핑 주입·규칙 적용·MultiEdit·경로탈출 차단·suffix 보존 검증됨.
  high-effort 코드리뷰(finder 4각 + 위치별 독립 검증) 반영: SessionStart gh 폴링을 `.claude/memory` 있을
  때만 실행, 머지 감지 정규식·명령 매칭 강건화, CLI IndexError·트랜스크립트 메모리·경로 fallback 정리.
- **live-fire 미검증** — 설치된 세션에서 훅이 실제로 발화하는지(discovery·matcher·`additionalContext` 도달·
  env 전파)는 이슈 #3 으로 이관. 현재 문서는 "구현됨"이지 "실세션 발화 검증됨"은 아니다.
