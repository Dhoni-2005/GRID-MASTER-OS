"""
memory_manager.py — Grid Master OS Kernel v1.2
Unified memory layer. Uses database._exec/_query abstractions.
No direct get_db() calls — all writes go through database helpers.

Phase 2 Step 1 additions:
  - _validate_tags()         — sanitise tag lists before storage
  - recall_by_tag()          — retrieve entries by exact tag match
  - list_known_tags()        — tag inventory for a project
  - recall_failures_by_tag() — failure_memory filtered by tag
  - remember() now validates tags before storage
"""
import database as db

_MODULE = "[MEMORY]"

SCORE_LOG      = 1
SCORE_RESULT   = 3
SCORE_PATTERN  = 5
SCORE_LESSON   = 7
SCORE_CRITICAL = 10


# ── TAG VALIDATION ────────────────────────────────────────────

def _validate_tags(tags: list | None) -> list[str]:
    """
    Sanitise a tag list before storage.
    - Accepts only string elements; non-strings are silently dropped.
    - Strips whitespace; empty strings dropped.
    - Deduplicates while preserving insertion order.
    - Returns empty list for None input.
    """
    if not tags:
        return []
    seen: set    = set()
    result: list = []
    for t in tags:
        if not isinstance(t, str):
            print(f"{_MODULE} Warning: non-string tag dropped: {t!r}")
            continue
        clean = t.strip()
        if not clean:
            continue
        if clean not in seen:
            seen.add(clean)
            result.append(clean)
    return result


# ── CORE WRITE ────────────────────────────────────────────────

def remember(task_id: int, content: str, entry_type: str = "log",
             tags: list | None = None, importance: int = SCORE_LOG,
             project_id: int | None = None, summary: str = "") -> int:
    """
    Store a memory entry. Tags are validated before storage.
    Every agent must call this before exiting a task.
    """
    try:
        return db.store_memory(
            task_id          = task_id,
            content          = content,
            entry_type       = entry_type,
            tags             = _validate_tags(tags),
            importance_score = importance,
            project_id       = project_id,
            summary          = summary,
        )
    except Exception as e:
        print(f"{_MODULE} Write error: {e}")
        return -1


def remember_failure(task_id: int, problem: str, cause: str = "",
                     fix: str = "", tags: list | None = None,
                     project_id: int | None = None) -> int:
    """
    Record a failure. Tags are validated before storage.
    The atomic composite write (failure_memory + memory_entry) is
    handled by grid_master via db.fail_task_atomic() at dispatch level.
    Direct callers still get the failure_memory row here.
    """
    try:
        return db.store_failure(
            task_id    = task_id,
            problem    = problem,
            cause      = cause,
            fix        = fix,
            tags       = _validate_tags(tags),
            project_id = project_id,
        )
    except Exception as e:
        print(f"{_MODULE} Failure write error: {e}")
        return -1


# ── CORE READ ─────────────────────────────────────────────────

def recall(task_id: int | None = None, project_id: int | None = None,
           min_importance: int = SCORE_LOG, limit: int = 20) -> list[dict]:
    """
    Retrieve memory entries, highest importance first.
    Planner calls this before creating a plan.
    """
    try:
        return db.get_memory(
            task_id    = task_id,
            project_id = project_id,
            min_score  = min_importance,
            limit      = limit,
        )
    except Exception as e:
        print(f"{_MODULE} Recall error: {e}")
        return []


def recall_failures(keyword: str, limit: int = 5) -> list[dict]:
    """Search failure memory by keyword."""
    try:
        return db.search_failures(keyword, limit=limit)
    except Exception as e:
        print(f"{_MODULE} Failure recall error: {e}")
        return []


def search(keyword: str, project_id: int | None = None,
           min_importance: int = SCORE_LOG, limit: int = 10) -> list[dict]:
    """Full-text search across memory entries."""
    try:
        return db.search_memory(
            keyword    = keyword,
            project_id = project_id,
            min_score  = min_importance,
            limit      = limit,
        )
    except Exception as e:
        print(f"{_MODULE} Search error: {e}")
        return []


# ── TAG QUERIES (Phase 2 — Step 1) ───────────────────────────

def recall_by_tag(tag: str,
                  project_id: int | None = None,
                  min_importance: int = SCORE_LOG,
                  limit: int = 20) -> list[dict]:
    """
    Return memory entries whose tags array contains `tag` exactly.
    Uses db.search_memory_by_tag() which leverages SQLite json_each().

    Example:
        entries = recall_by_tag("flask", project_id=1)
        # returns only entries tagged exactly "flask"
    """
    try:
        tag = tag.strip()
        if not tag:
            print(f"{_MODULE} recall_by_tag: empty tag, returning []")
            return []
        return db.search_memory_by_tag(
            tag        = tag,
            project_id = project_id,
            min_score  = min_importance,
            limit      = limit,
        )
    except Exception as e:
        print(f"{_MODULE} recall_by_tag error: {e}")
        return []


def list_known_tags(project_id: int | None = None) -> list[str]:
    """
    Return all distinct tag values stored across memory_entries.
    Optionally scoped to a project.
    Useful for: discovery, auto-suggest, compression grouping.

    Example:
        tags = list_known_tags(project_id=1)
        # ["flask", "python", "lesson", "failure"]
    """
    try:
        return db.list_tags(project_id=project_id)
    except Exception as e:
        print(f"{_MODULE} list_known_tags error: {e}")
        return []


def recall_failures_by_tag(tag: str, limit: int = 10) -> list[dict]:
    """
    Return failure_memory entries whose tags array contains `tag` exactly.
    Planner can use this to find all known failures in a topic area.

    Example:
        failures = recall_failures_by_tag("flask")
        # returns failures tagged with "flask"
    """
    try:
        tag = tag.strip()
        if not tag:
            print(f"{_MODULE} recall_failures_by_tag: empty tag, returning []")
            return []
        return db.search_failures_by_tag(tag=tag, limit=limit)
    except Exception as e:
        print(f"{_MODULE} recall_failures_by_tag error: {e}")
        return []


# ── KNOWLEDGE BASE ────────────────────────────────────────────

def extract_knowledge(topic: str, content: str, summary: str = "",
                      source: str = "", tags: list | None = None) -> int:
    """
    Knowledge Extractor hook. Stores reusable patterns in knowledge_base.
    Phase 2: called by Memory Manager after Reviewer approval.
    Tags are validated before storage.
    """
    try:
        return db.store_knowledge(
            topic   = topic,
            content = content,
            summary = summary,
            source  = source,
            tags    = _validate_tags(tags),
        )
    except Exception as e:
        print(f"{_MODULE} Knowledge extract error: {e}")
        return -1


def recall_knowledge(query: str, limit: int = 5) -> list[dict]:
    """Search the knowledge base. Worker calls this before executing a task."""
    try:
        return db.search_knowledge(query, limit=limit)
    except Exception as e:
        print(f"{_MODULE} Knowledge recall error: {e}")
        return []


# ── CONTEXT BUILDER ───────────────────────────────────────────

def build_context(task_id: int, project_id: int | None = None,
                  keyword: str = "", limit: int = 10) -> dict:
    """
    Assemble bounded context for the Planner before execution.
    Returns recent memories, relevant failures, and knowledge.
    Never returns more than `limit` entries per section.
    """
    context: dict = {"memories": [], "failures": [], "knowledge": []}
    try:
        context["memories"] = recall(
            project_id     = project_id,
            min_importance = SCORE_RESULT,
            limit          = limit,
        )
        if keyword:
            context["failures"]  = recall_failures(keyword, limit=5)
            context["knowledge"] = recall_knowledge(keyword, limit=5)
    except Exception as e:
        print(f"{_MODULE} Context build error: {e}")
    return context


# ── SUMMARIZATION PLACEHOLDER ─────────────────────────────────

def summarize_memory(project_id: int, keep_top: int = 50) -> str:
    """
    Placeholder for Phase 2 Step 4 rule-based summarization.
    Phase 3 will replace _build_digest() with an LLM API call.
    """
    try:
        entries = db.get_memory(project_id=project_id, limit=200)
        if len(entries) <= keep_top:
            return f"{_MODULE} Memory within limits — no summarization needed."
        low    = entries[keep_top:]
        digest = " | ".join(e["content"][:60] for e in low)
        summary = f"[AUTO-SUMMARY] Compressed {len(low)} entries: {digest[:400]}"
        if entries:
            remember(
                task_id    = entries[0].get("task_id") or 0,
                content    = summary,
                entry_type = "summary",
                importance = SCORE_LESSON,
                project_id = project_id,
                summary    = f"Auto-summary of {len(low)} entries",
            )
        return summary
    except Exception as e:
        print(f"{_MODULE} Summarize error: {e}")
        return ""


# ── MEMORY STATS ──────────────────────────────────────────────

def memory_stats(project_id: int | None = None) -> dict:
    """Return memory health for the dashboard or Coordinator."""
    try:
        entries  = db.get_memory(project_id=project_id, limit=10000)
        failures = db.search_failures("", limit=10000)
        buckets  = {1: 0, 3: 0, 5: 0, 7: 0, 10: 0}
        for e in entries:
            s = e.get("importance_score", 1)
            b = min(buckets.keys(), key=lambda x: abs(x - s))
            buckets[b] += 1
        return {
            "total_entries":      len(entries),
            "total_failures":     len(failures),
            "score_distribution": buckets,
        }
    except Exception as e:
        print(f"{_MODULE} Stats error: {e}")
        return {}


# ── SELF-TEST ─────────────────────────────────────────────────
if __name__ == "__main__":
    import os, tempfile, importlib, sys

    tmp = tempfile.mktemp(suffix=".db")
    os.environ["GRIDMASTER_DB"] = tmp
    for mod in ["database", "memory_manager"]:
        if mod in sys.modules:
            importlib.reload(sys.modules[mod])
    import database as _db
    _db.init_db()

    pid = _db.create_project("MM v1.2 Test", "memory_manager Phase 2 Step 1")
    tid = _db.create_task(pid, "Tag memory test", priority=5)

    # ── Phase 1 existing tests (must still pass) ──────────────
    remember(tid, "Started", importance=SCORE_LOG, project_id=pid)
    remember(tid, "Worker ran Flask route", importance=SCORE_RESULT,
             project_id=pid, tags=["flask", "python"])
    remember_failure(tid, "ImportError: flask", cause="missing dep",
                     fix="pip install flask", tags=["python", "flask"],
                     project_id=pid)
    extract_knowledge("flask_health",
                      "@app.route('/health')\ndef h(): return jsonify({})",
                      summary="Flask health pattern", tags=["flask"])
    ctx = build_context(tid, project_id=pid, keyword="flask")
    assert ctx["memories"], "Expected memories in context"
    stats = memory_stats(project_id=pid)
    assert stats["total_entries"] >= 2, "Expected >=2 entries"

    # ── Phase 2 Step 1: tag validation ────────────────────────
    clean = _validate_tags(["python", "  flask  ", 123, "", "python"])
    assert clean == ["python", "flask"], f"Tag validation failed: {clean}"

    # ── Phase 2 Step 1: recall_by_tag ─────────────────────────
    flask_entries = recall_by_tag("flask", project_id=pid)
    assert len(flask_entries) >= 1, \
        f"Expected >=1 flask-tagged entry, got {len(flask_entries)}"
    for e in flask_entries:
        import json
        assert "flask" in json.loads(e["tags"]), \
            f"Entry {e['id']} missing flask tag: {e['tags']}"

    python_entries = recall_by_tag("python", project_id=pid)
    assert len(python_entries) >= 1, \
        f"Expected >=1 python-tagged entry, got {len(python_entries)}"

    # ── Phase 2 Step 1: list_known_tags ───────────────────────
    known = list_known_tags(project_id=pid)
    assert "flask"  in known, f"'flask' not in known tags: {known}"
    assert "python" in known, f"'python' not in known tags: {known}"

    # ── Phase 2 Step 1: recall_failures_by_tag ────────────────
    flask_fails = recall_failures_by_tag("flask")
    assert len(flask_fails) >= 1, \
        f"Expected >=1 flask failure, got {len(flask_fails)}"

    # ── Edge cases ────────────────────────────────────────────
    assert recall_by_tag("") == [], "Empty tag should return []"
    assert recall_failures_by_tag("") == [], "Empty tag should return []"
    no_match = recall_by_tag("nonexistent_tag_xyz")
    assert no_match == [], f"Non-existent tag should return [], got {no_match}"

    _db.close_db()
    os.remove(tmp)
    print(f"{_MODULE} Self-test passed (Phase 2 Step 1 — Tag Memory).")
