---
name: no-absolute-time-in-fixtures
description: Never hardcode an absolute timestamp in a test fixture for code that looks at a recency window (cutoff) — once the date passes, CI breaks with no code change
type: project
---

Session log discovery only looks at the **last N days** — `_recent_codex_rollouts(days=30)` and
`_has_project_codex_rollout(days=30)` in `handoff.py`, and the `--since` parsing in `history`.
Test fixtures for such code **must not stamp an absolute epoch with `os.utime`.** Build them
relative to `time.time()` and pin only the **relative ordering** the test actually asserts (A is
older than B).

**Why:** `tests/test_handoff_transcript_scope.py` hardcoded `self.now = 1_785_000_000.0`, which
is 2026-07-25 17:20 UTC. On 2026-08-22 that was about 27 days old — still inside the 30-day
window, and CI was green. On 2026-08-31 it was about 36 days old, the fixture fell outside the
window, and 5 unit tests on main broke **without a single commit**. With no causing commit, the
diff shows nothing, and comparing against the last green commit does not help either.

The margin is the point: a fixture can sit just inside the window for weeks and still be a bomb.
This one had roughly three days of slack left on the last green run.

Review does not catch this failure. It passes when written, it is merged while passing, and it
breaks on a day nobody touched it. `tests/test_fw_live_session.py` had the same shape — the same
bomb, just not gone off yet (both fixed in #128).

**How to apply:**

```python
# ❌ breaks by itself once the date passes
self.now = 1_785_000_000.0

# ✅ stays inside the window, keeps the relative ordering
self.now = time.time() - 86400.0        # yesterday
_write_rollout(..., self.now - 3600)    # one hour older than that
```

- When a new test creates an mtime or a timestamp, **always base it on `time.time()`**.
- If the test **deliberately** exercises the outside of the window, make that relative too
  (`time.time() - 40*86400`) — that way the intent survives a change to the `days` default.
- When you do have to reason about an absolute epoch, convert it explicitly in UTC
  (`datetime.fromtimestamp(ts, timezone.utc)`) and write the timezone down. A local-time reading
  of the same number moves the date and makes the age arithmetic wrong.
- Date directories (`~/.codex/sessions/2026/08/11/`) may stay fixed. Discovery walks the whole
  tree with `os.walk` and looks **only at mtime**. It is always the mtime that trips you up.

Related: [[build-drift]]
