#!/usr/bin/env python3
"""Deferred Codex reflection, shared across adapters and worktrees.

One successful snapshot per session. A process lock releases on crashes; failures can retry.
State is local to the common Git directory and snapshots are removed after the worker exits.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

from compact_transcript import _codex_typed_session
try:
    from repo_identity import git_common_dir, worktree_roots
except ImportError:
    git_common_dir = lambda _path: None
    worktree_roots = lambda _path: []

MIN_IDLE_SECONDS = 30 * 60
MAX_ATTEMPTS = 3
RETRY_SECONDS = 60 * 60


def metadata(path):
    try:
        with open(path, encoding='utf-8') as stream:
            data = json.loads(stream.readline())
        return data if data.get('type') == 'session_meta' else None
    except (OSError, ValueError, AttributeError, TypeError):
        return None


def eligible(path):
    meta = metadata(path)
    return bool(meta and _codex_typed_session(meta) and meta['payload'].get('id'))


def backend_available():
    backend = os.environ.get('REFLECT_BACKEND', 'claude')
    if backend == 'claude':
        return bool(shutil.which('claude'))
    if backend == 'deepseek':
        return bool(os.environ.get('DEEPSEEK_API_KEY'))
    # Ollama is an HTTP service; connectivity is checked by the worker/backend.
    return backend == 'ollama'


def job_dir(project_dir, transcript):
    meta = metadata(transcript)
    common = git_common_dir(project_dir)
    if not common or not meta or not meta.get('payload', {}).get('id'):
        return None
    key = hashlib.sha256(str(meta['payload']['id']).encode()).hexdigest()
    return Path(common) / 'agent-harness' / 'codex-reflect-jobs' / key


def completed(project_dir, transcript):
    directory = job_dir(project_dir, transcript)
    return bool(directory and (directory / 'done.json').is_file())


def primary_project(project_dir):
    roots = worktree_roots(project_dir)
    common = git_common_dir(project_dir)
    if not roots or not common:
        return None
    # Bare repositories have no persistent primary working tree. Do not silently choose
    # an arbitrary linked worktree for durable drafts.
    result = subprocess.run(['git', 'rev-parse', '--absolute-git-dir'], cwd=roots[0],
                            capture_output=True, text=True, timeout=5)
    if result.returncode or Path(result.stdout.strip()).resolve() != Path(common).resolve():
        return None
    return roots[0] if (Path(roots[0]) / '.claude/memory').is_dir() else None


def _attempts(directory):
    try:
        value = json.loads((directory / 'attempts.json').read_text())
        if (not isinstance(value, dict) or type(value.get('count')) is not int
                or not 0 <= value['count'] <= MAX_ATTEMPTS
                or type(value.get('at')) not in (int, float)):
            raise ValueError('bad attempt state')
        return value
    except FileNotFoundError:
        return {'count': 0, 'at': 0}
    except (OSError, ValueError):
        # Do not turn a corrupt cost ledger into unlimited paid retries.
        return {'count': MAX_ATTEMPTS, 'at': 0}


def _ready(directory):
    if (directory / 'done.json').exists() or (directory / 'skipped.json').exists():
        return False
    state = _attempts(directory)
    return (state['count'] < MAX_ATTEMPTS and
            time.time() >= state['at'] + (RETRY_SECONDS * 2 ** (state['count'] - 1) if state['count'] else 0))


def available(project_dir, transcript):
    directory = job_dir(project_dir, transcript)
    return bool(directory and _ready(directory) and backend_available() and primary_project(project_dir))


def _write_json(path, value):
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as out:
        temporary = Path(out.name)
        json.dump(value, out)
        out.flush()
        os.fsync(out.fileno())
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _lock(stream):
    """Nonblocking OS lock, released even if the worker is killed."""
    if os.name == 'nt':
        import msvcrt
        stream.seek(0)
        if not stream.read(1):
            stream.write(b'0'); stream.flush()
        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _fingerprint(stat):
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns


def run(project_dir, transcript):
    if not eligible(transcript) or not backend_available():
        return False
    directory = job_dir(project_dir, transcript)
    destination = primary_project(project_dir)
    if not directory or not destination or not (Path(destination) / '.claude/memory').is_dir():
        return False
    directory.mkdir(parents=True, exist_ok=True)
    with open(directory / 'lock', 'a+b') as lock:
        try:
            _lock(lock)
        except OSError:
            return False  # another adapter/worker owns this session
        if (directory / 'done.json').is_file():
            return True
        if not _ready(directory):
            return False
        source = Path(transcript)
        before = source.stat()
        if before.st_mtime > time.time() - MIN_IDLE_SECONDS:
            return False  # resumed after discovery
        snapshot = directory / 'snapshot.jsonl'
        try:
            with source.open('rb') as inp, snapshot.open('wb') as out:
                shutil.copyfileobj(inp, out)
            if _fingerprint(before) != _fingerprint(source.stat()):
                return False  # changing while copied; retry at a later session start
            # Ignore an unfinished last JSONL record; never pass a torn record to the compactor.
            with snapshot.open('r+b') as stream:
                stream.seek(0, 2)
                end = stream.tell()
                while end:
                    start = max(0, end - 8192)
                    stream.seek(start)
                    block = stream.read(end - start)
                    newline = block.rfind(b'\n')
                    if newline >= 0:
                        stream.truncate(start + newline + 1)
                        break
                    end = start
                else:
                    stream.truncate(0)
            from compact_transcript import compact
            body, _ = compact(str(snapshot), require_attributed_user=True)
            if not body.strip():
                _write_json(directory / 'skipped.json', {'reason': 'no attributable user input'})
                return False
            state = _attempts(directory)
            _write_json(directory / 'attempts.json', {'count': state['count'] + 1, 'at': time.time()})
            script = Path(__file__).with_name('reflect.py')
            env = {**os.environ, 'REFLECT_JOB': '1', 'CLAUDE_PROJECT_DIR': destination}
            result = subprocess.run([sys.executable, str(script), '--transcript', str(snapshot)],
                                    cwd=destination, env=env, timeout=660,
                                    **({'pass_fds': (lock.fileno(),)} if os.name != 'nt' else {}))
            if result.returncode:
                return False
            # Atomic completion marker; only a successful worker suppresses future attempts.
            _write_json(directory / 'done.json', {'completed_at': time.time(), 'bytes': before.st_size})
            return True
        finally:
            snapshot.unlink(missing_ok=True)


def launch(project_dir, transcript):
    if not eligible(transcript) or not backend_available():
        return False
    if completed(project_dir, transcript):
        return True
    if not available(project_dir, transcript):
        return False
    log_path = Path(project_dir) / '.claude/.cache/reflect.log'
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open('a', encoding='utf-8') as log:
        subprocess.Popen([sys.executable, str(Path(__file__).resolve()),
                          '--project-dir', project_dir, '--transcript', transcript],
                         cwd=project_dir, env={**os.environ, 'REFLECT_JOB': '1'},
                         stdout=log, stderr=log, start_new_session=True)
    return True


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--project-dir', required=True)
    parser.add_argument('--transcript', required=True)
    args = parser.parse_args()
    try:
        success = run(args.project_dir, args.transcript)
        print('[codex-reflect] completed or already done' if success else '[codex-reflect] deferred or failed; retry on a later session start', file=sys.stderr)
    except Exception as exc:
        print(f'[codex-reflect] {type(exc).__name__}; retry on a later session start', file=sys.stderr)
        sys.exit(1)
