# agent-harness

**Claude Code + Codex** 를 위한 재사용 가능한 에이전트 하네스.
핸드오프, 자기개선 회고, 커밋되어 공유되는 메모리, 워크플로 스킬을 한 번에 배포한다.
시각 개요(그림 포함)는 [docs/overview.html](docs/overview.html) 참고.

> 설치 방식은 툴마다 다르다(**아래 비대칭 참고**). 호출 모델도 다르다 —
> **Claude**는 슬래시 커맨드(`/handoff-save` …), **Codex**는 설명(description) 매칭으로 트리거되는 skill.
> 개념·이름은 맞추되 슬래시 표기가 양쪽에서 동일 보장되진 않는다.

## 왜 다른가 (차별점)

공개 하네스 대부분은 *세션 종료 시 캡처*까지만 한다. 이 하네스는:
- **자기개선 훅 루프** — 편집 전 관련 메모리 주입 → 편집 후 품질 경고 → 머지 시 회고 → 승격. 스킬보다 한 층 위의 자동 루프. ([상세](docs/self-improvement-hooks.md))
- **PR 머지 트리거 회고** — 세션 끝이 아니라 작업이 머지될 때 교훈을 남긴다.
- **커밋되어 크로스머신/툴 공유되는 메모리** — transcript(로컬·툴 종속) 대신 git 에 커밋되는 메모리·핸드오프로 다른 머신·사람·툴이 이어받는다.
- **governance 내장** — `_pending → 사람 승인 → committed`. 잘못된 교훈·민감정보가 자동으로 박히지 않는다.

## 설치 (비대칭 — 툴마다 다름)

### Claude Code (플러그인 한 방)
```
/plugin marketplace add foxyberry/agent-harness
/plugin install agent-harness@foxyberry
```
로컬 테스트: `/plugin marketplace add ./` (repo 루트에서)

### Codex (skill-only plugin) — *installer 구축 중*
```
codex plugin marketplace add foxyberry/agent-harness   # (배포 후)
codex plugin add agent-harness@foxyberry
# 또는 로컬: codex plugin marketplace add ./
```
`installers/install-codex.sh`(config.toml merge)는 아직 미구현 — 현재는 위 marketplace 방식.

### 업데이트

일반 사용자는 설치 후 계속 쓰면 된다. 새 릴리스가 필요할 때만 marketplace snapshot 을 갱신하고
플러그인 캐시를 다시 받는다.

```bash
codex plugin marketplace upgrade foxyberry
codex plugin remove agent-harness@foxyberry
codex plugin add agent-harness@foxyberry
```

개발 중 로컬 dogfooding 은 repo 루트에서 `./build.sh` 후 `codex plugin marketplace add ./` 를 쓰고,
사용자에게는 버전된 릴리스 단위로 업데이트를 안내한다.

### 공통 (프로젝트 층)
프로젝트 repo 에 `project-template/` 를 복사 — `AGENTS.md`(정본) + `CLAUDE.md`(@import) + `.claude/memory/` 템플릿.

## 구조 (3층)

| 층 | 위치 | 내용 |
|----|------|------|
| **core** | `core/` | 툴 무관 정본 — Agent Skills(`SKILL.md`), 스크립트, 메모리 스키마, 핸드오프 포맷 |
| **adapter** | `plugins/harness/` (Claude), `plugins/codex/` (Codex) | core 를 각 툴로 포장 (build.sh 로 **복사 생성**) |
| **opinion pack** | `project-template/`, 문서 | 개인/팀 워크플로·회고 방식 (취향 — 선택 채택) |

`core/` 가 정본이고 어댑터는 생성물이다. 수정은 core 에서 → `./build.sh` → 어댑터 재생성.

## 명령 (설치 후)

| 명령 | 하는 일 |
|------|---------|
| `/handoff-save` | 넘기기 전 이식 가능한 상태를 커밋 파일로 저장 |
| `/handoff-load` | 이어받기 — 커밋된 핸드오프 1순위 + 현재 git 대조 |
| `/feedback-review` | 받은 지적을 규칙/스킬로 승격 검토 |
| `/memory-update` | 배운 것을 공유 메모리로 영속화 (`_pending` 검토·승격) |

## 자동 훅 (Claude 어댑터)

명령과 별개로, 배경에서 도는 **자기개선 훅**이 있다 ([상세 가이드](docs/self-improvement-hooks.md)):

| 훅 | 이벤트 | 하는 일 | 프로젝트 설정 |
|----|--------|---------|---------------|
| memory-search | 편집 전 | 파일에 맞는 메모리를 컨텍스트에 주입 | `.claude/memory/routes.json` |
| reflection | 편집 후 | 코드 품질 경고(정규식 규칙 + 내장 TODO/FIXME) | `.claude/memory/reflection-rules.json` |
| pr-merge-reflect | 머지·세션시작·발화 | 미회고 PR 리마인더 + (opt-in) 자동 회고 초안 | env `HARNESS_AUTO_REFLECT=1` |

엔진은 core, "무엇을" 주입·경고할지는 프로젝트 데이터가 정한다. 설정이 없으면 조용히 no-op.
자동 회고 잡은 `claude -p` 를 띄우므로 **기본 꺼짐**(`HARNESS_AUTO_REFLECT` opt-in). Codex 훅은 defer.

## 개발

```bash
./build.sh    # core → 어댑터 재생성. 커밋 전 항상.
```
CI(`.github/workflows/validate.yml`)가 JSON·스크립트 문법 + **core↔adapter 동기화**(build.sh 안 돌린 채 커밋 방지)를 검증한다.

## 상태

구축 중.
- ✅ Claude 어댑터 — handoff·feedback-review·memory-update 스킬 + 자기개선 훅(memory-search·reflection·pr-merge-reflect) 구현·스모크테스트 완료
- ✅ Codex 스킬 로드 live 검증 — 4개 스킬 정상 노출, Claude 전용 frontmatter 필드는 무해(무시됨) ([이슈 #3](https://github.com/foxyberry/agent-harness/issues/3) 기록)
- 🔜 훅 live-fire 검증(설치 후 실발화)·Codex 스킬 실행 검증 — 이슈 #3
- 🔜 Codex 어댑터 훅(버전 취약으로 defer)·installer(config merge)·governance 자동화
