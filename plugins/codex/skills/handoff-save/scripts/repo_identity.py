#!/usr/bin/env python3
"""저장소 identity 판정 — 세션 로그의 cwd 가 "이 프로젝트의 작업 공간인가" 를 결정한다.

왜 필요한가:
  에이전트 병렬 작업은 `git worktree` 로 워킹트리를 분리하는데, worktree 는 **프로젝트
  폴더 바깥**에 생기는 게 정상이다:
    - Codex Desktop  : `~/.codex/worktrees/<hash>/`
    - 사용자 관례     : `<repo 의 형제>/.agent-worktrees/<name>/`
    - 임의 지정       : 사용자가 아무 경로나 줄 수 있다
  경로 prefix(`cwd.startswith(project_dir + os.sep)`) 로 판정하면 이 전부가 "남의
  프로젝트" 로 탈락한다. 실제로 이 저장소의 PR #72 회고가 그렇게 통째로 누락됐다.

접근:
  경로를 비교하지 않고 **git 에게 직접 묻는다** — `git rev-parse --git-common-dir` 은
  worktree 가 어디 있든 원본 저장소의 `.git` 을 가리킨다. 그 값이 같으면 같은 저장소다.

  cwd 가 이미 지워졌으면(worktree 제거 후) 물어볼 대상이 없다. 그래서 관측 시점마다
  `worktree 경로 → identity` 를 alias 캐시에 적어두고, 사라진 뒤에는 그걸로 되짚는다.
  **한 번도 관측되지 않은 채 사라진 worktree 는 복구 불가** — 추정하지 않는다(오탐 방지).

사용:
  m = ProjectMatcher(project_dir)
  m.belongs(cwd)          # → bool
  m.record_worktrees()    # 현재 worktree 들을 alias 캐시에 기록(관측)
"""
import json
import os
import subprocess
import time

GIT_TIMEOUT = 5           # git 호출 상한 — 훅에서 도므로 절대 매달리면 안 된다
ALIAS_RETAIN_DAYS = 90    # alias 보존 기간. 제거된 worktree 를 이 기간 동안 되짚을 수 있다


def _norm(path):
    """경로 정규화. symlink·`..`·trailing slash·대소문자 차이를 흡수한다.

    startswith 비교가 깨지는 주된 이유가 이 정규화 부재였다(macOS 의 `/tmp` →
    `/private/tmp` symlink 가 대표적)."""
    if not path:
        return None
    try:
        return os.path.normcase(os.path.realpath(path))
    except (OSError, ValueError):
        return None


def _git(args, cwd):
    """git 호출 → stdout 문자열. 실패·타임아웃·git 부재는 전부 None(예외 안 냄)."""
    try:
        r = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    return r.stdout.strip()


def git_common_dir(path):
    """`path` 가 속한 저장소의 공통 .git 디렉터리(정규화된 절대경로). 저장소가 아니면 None.

    linked worktree 에서 실행해도 **원본 저장소의 .git** 을 돌려준다 — 이게 identity 다.
    (`--git-dir` 은 worktree 마다 다른 `.git/worktrees/<name>` 을 주므로 쓰면 안 된다.)"""
    if not path or not os.path.isdir(path):
        return None
    out = _git(["rev-parse", "--path-format=absolute", "--git-common-dir"], path)
    if not out:
        # 구버전 git 은 --path-format 을 모른다 → 상대경로로 나올 수 있으니 cwd 기준 해석
        out = _git(["rev-parse", "--git-common-dir"], path)
        if out and not os.path.isabs(out):
            out = os.path.join(path, out)
    return _norm(out) if out else None


def worktree_roots(project_dir):
    """이 저장소에 등록된 모든 worktree 루트(정규화 경로) 리스트.

    porcelain 포맷은 `worktree <path>` 줄로 시작하는 레코드 나열이다. 경로에 공백이
    들어갈 수 있으므로 split() 이 아니라 **접두사 제거**로 파싱한다.
    `bare` 레코드는 워킹트리가 아니므로 제외한다. `prunable`·`locked`·detached 는
    여전히 실재하는 워킹트리이므로 **제외하지 않는다**."""
    out = _git(["worktree", "list", "--porcelain"], project_dir)
    if not out:
        return []
    roots, current, is_bare = [], None, False
    for line in out.splitlines():
        if line.startswith("worktree "):
            if current and not is_bare:
                roots.append(current)
            current, is_bare = _norm(line[len("worktree "):]), False
        elif line.strip() == "bare":
            is_bare = True
    if current and not is_bare:
        roots.append(current)
    return [r for r in roots if r]


class ProjectMatcher:
    """cwd 가 이 프로젝트의 작업 공간인지 판정한다. git 호출은 캐시·메모이즈한다.

    한 번의 스윕에서 rollout 수백 개의 cwd 를 검사하므로, 매번 git 을 부르면 비싸다.
    - worktree 목록: 인스턴스당 1회
    - cwd → identity: 경로별 메모이즈
    """

    def __init__(self, project_dir, alias_path=None):
        self.project_dir = _norm(project_dir)
        self.identity = git_common_dir(project_dir) if project_dir else None
        self._alias_path = alias_path or _default_alias_path(project_dir, self.identity)
        self._roots = None          # lazy: worktree_roots()
        self._alias = None          # lazy: 디스크 캐시
        self._identity_cache = {}   # cwd(정규화) → identity|None

    # ---------- 내부 lazy 로더 ----------

    def _get_roots(self):
        if self._roots is None:
            self._roots = set(worktree_roots(self.project_dir)) if self.project_dir else set()
            if self.project_dir:
                self._roots.add(self.project_dir)
        return self._roots

    def _get_alias(self):
        if self._alias is None:
            self._alias = _load_alias(self._alias_path)
        return self._alias

    def _identity_of(self, cwd_norm):
        if cwd_norm not in self._identity_cache:
            self._identity_cache[cwd_norm] = git_common_dir(cwd_norm)
        return self._identity_cache[cwd_norm]

    # ---------- 공개 API ----------

    def belongs(self, cwd):
        """cwd 가 이 프로젝트의 워킹트리(본체 또는 worktree)면 True.

        판정 순서 — 확실한 근거부터:
          1. 살아있는 경로면 git 에게 identity 를 묻는다 (가장 정확)
          2. 등록된 worktree 루트와 일치/포함 (git 호출 실패 대비)
          3. alias 캐시 (경로가 사라진 경우의 유일한 근거)
        어느 것도 못 맞추면 False — 추정하지 않는다."""
        cwd_norm = _norm(cwd)
        if not cwd_norm or not self.project_dir:
            return False

        # 1) 살아있는 경로 → git 에 직접 질의. worktree 위치와 무관하게 정확하다.
        if os.path.isdir(cwd_norm):
            ident = self._identity_of(cwd_norm)
            if ident and self.identity:
                return ident == self.identity
            # git 이 없거나 저장소가 아니면 아래 경로 기반 판정으로 넘어간다

        # 2) 등록된 worktree 루트 기준 포함 관계.
        #    startswith 가 아니라 commonpath — `/a/b` 가 `/a/bc` 를 삼키는 버그를 막는다.
        for root in self._get_roots():
            if cwd_norm == root or _is_within(cwd_norm, root):
                return True

        # 3) 사라진 worktree → 과거 관측 기록으로 되짚는다.
        alias = self._get_alias()
        if alias.get("identity") and self.identity and alias["identity"] == self.identity:
            for path in alias.get("roots", {}):
                if cwd_norm == path or _is_within(cwd_norm, path):
                    return True
        return False

    def record_worktrees(self):
        """현재 worktree 들을 alias 캐시에 관측 기록한다. 제거된 뒤에도 되짚기 위함.

        SessionStart 처럼 정기적으로 도는 지점에서 부른다. 오래된 기록은 만료시킨다.
        실패해도 조용히 넘어간다 — 관측 실패가 회고를 막으면 안 된다."""
        if not self.identity:
            return False
        alias = self._get_alias()
        if alias.get("identity") != self.identity:
            alias = {"identity": self.identity, "roots": {}}
        now = time.time()
        for root in self._get_roots():
            alias["roots"][root] = now
        cutoff = now - ALIAS_RETAIN_DAYS * 86400
        alias["roots"] = {p: ts for p, ts in alias["roots"].items() if ts >= cutoff}
        self._alias = alias
        return _save_alias(self._alias_path, alias)


def _is_within(child, parent):
    """child 가 parent 하위인가. commonpath 기반 — 문자열 prefix 오탐이 없다."""
    if not child or not parent:
        return False
    try:
        return os.path.commonpath([child, parent]) == parent and child != parent
    except ValueError:  # 다른 드라이브 등 공통 경로가 없는 경우
        return False


def _default_alias_path(project_dir, identity=None):
    """alias 캐시 위치 = **git 공통 디렉터리 안**(`<repo>/.git/agent-harness/`).

    프로젝트 폴더의 `.claude/.cache/` 에 두면 안 된다: `project_dir` 자체가 linked worktree
    일 때 캐시가 그 worktree 안에 생기고, **worktree 를 지우면 캐시도 같이 사라진다** —
    되짚으려고 만든 기록이 되짚어야 할 순간에 없어지는 셈이다. 게다가 본체 체크아웃은
    다른 캐시를 읽어 서로 못 본다.

    git 공통 디렉터리는 모든 worktree 가 공유하고, worktree 제거와 무관하게 살아남고,
    커밋 대상도 아니다(절대경로가 저장소에 박히지 않는다)."""
    common = identity or git_common_dir(project_dir)
    if common:
        return os.path.join(common, "agent-harness", "worktree-alias.json")
    if not project_dir:
        return None
    # git 저장소가 아니면(테스트·비정상 상태) 프로젝트 로컬 캐시로 폴백
    return os.path.join(project_dir, ".claude", ".cache", "worktree-alias.json")


def _load_alias(path):
    if not path or not os.path.exists(path):
        return {"identity": None, "roots": {}}
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict) and isinstance(d.get("roots"), dict):
            return d
    except (OSError, ValueError):
        pass
    return {"identity": None, "roots": {}}


def _save_alias(path, alias):
    if not path:
        return False
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(alias, f, ensure_ascii=False, indent=2)
        return True
    except OSError:
        return False
