"""
memory_manager.py — Grid Master OS Kernel v1.1
Unified memory layer. Uses database._exec/_query abstractions.
No direct get_db() calls — all writes go through database helpers.
"""
import database as db

_MODULE = "[MEMORY]"

SCORE_LOG      = 1
SCORE_RESULT   = 3
SCORE_PATTERN  = 5
SCORE_LESSON   = 7
SCORE_CRITICAL = 10


def remember(task_id: int, content: str, entry_type: str = "log",
             tags: list | None = None, importance: int = SCORE_LOG,
             project_id: int | None = None, summary: str = "") -> int:
    try:
        return db.store_memory(task_id=task_id, content=content,
                               entry_type=entry_type, tags=tags or [],
                               importance_score=importance,
                               project_id=project_id, summary=summary)
    except Exception as e:
        print(f"{_MODULE} Write error: {e}")
        return -1


def remember_failure(task_id: int, problem: str, cause: str = "",
                     fix: str = "", tags: list | None = None,
                     project_id: int | None = None) -> int:
    """
    Record failure. Uses db.store_failure only — the atomic
    composite write (failure_memory + memory_entry) is handled
    by grid_master via db.fail_task_atomic() at dispatch level.
    Direct callers still get the failure_memory row here.
    """
    try:
        return db.store_failure(task_id=task_id, problem=problem,
                                cause=cause, fix=fix,
                                tags=tags or [], project_id=project_id)
    except Exception as e:
        print(f"{_MODULE} Failure write error: {e}")
        return -1


def recall(task_id: int | None = None, project_id: int | None = None,
           min_importance: int = SCORE_LOG, limit: int = 20) -> list[dict]:
    try:
        return db.get_memory(task_id=task_id, project_id=project_id,
                             min_score=min_importance, limit=limit)
    except Exception as e:
        print(f"{_MODULE} Recall error: {e}")
        return []


def recall_failures(keyword: str, limit: int = 5) -> list[dict]:
    try:
        return db.search_failures(keyword, limit=limit)
    except Exception as e:
        print(f"{_MODULE} Failure recall error: {e}")
        return []


def search(keyword: str, project_id: int | None = None,
           min_importance: int = SCORE_LOG, limit: int = 10) -> list[dict]:
    try:
        return db.search_memory(keyword=keyword, project_id=project_id,
                                min_score=min_importance, limit=limit)
    except Exception as e:
        print(f"{_MODULE} Search error: {e}")
        return []


def extract_knowledge(topic: str, content: str, summary: str = "",
                      source: str = "", tags: list | None = None) -> int:
    """
    Knowledge Extractor hook — called by Memory Manager after
    Reviewer approval. Stores reusable patterns in knowledge_base.
    Phase 2 will connect this to the Reviewer agent directly.
    """
    try:
        return db.store_knowledge(topic=topic, content=content,
                                  summary=summary, source=source,
                                  tags=tags or [])
    except Exception as e:
        print(f"{_MODULE} Knowledge extract error: {e}")
        return -1


def recall_knowledge(query: str, limit: int = 5) -> list[dict]:
    try:
        return db.search_knowledge(query, limit=limit)
    except Exception as e:
        print(f"{_MODULE} Knowledge recall error: {e}")
        return []


def build_context(task_id: int, project_id: int | None = None,
                  keyword: str = "", limit: int = 10) -> dict:
    """
    Assemble bounded context for the Planner before execution.
    Never returns more than `limit` entries per section.
    Phase 2 Planner calls this as its first action.
    """
    context: dict = {"memories": [], "failures": [], "knowledge": []}
    try:
        context["memories"] = recall(project_id=project_id,
                                     min_importance=SCORE_RESULT, limit=limit)
        if keyword:
            context["failures"]  = recall_failures(keyword, limit=5)
            context["knowledge"] = recall_knowledge(keyword, limit=5)
    except Exception as e:
        print(f"{_MODULE} Context build error: {e}")
    return context


def summarize_memory(project_id: int, keep_top: int = 50) -> str:
    """
    Placeholder for LLM-powered summarization (Phase 3).
    Current: keeps top-N by importance, digests the rest into one entry.
    """
    try:
        entries = db.get_memory(project_id=project_id, limit=200)
        if len(entries) <= keep_top:
            return f"{_MODULE} Memory within limits — no summarization needed."
        low = entries[keep_top:]
        digest = " | ".join(e["content"][:60] for e in low)
        summary = f"[AUTO-SUMMARY] Compressed {len(low)} entries: {digest[:400]}"
        if entries:
            remember(task_id=entries[0].get("task_id") or 0,
                     content=summary, entry_type="summary",
                     importance=SCORE_LESSON, project_id=project_id,
                     summary=f"Auto-summary of {len(low)} entries")
        return summary
    except Exception as e:
        print(f"{_MODULE} Summarize error: {e}")
        return ""


def memory_stats(project_id: int | None = None) -> dict:
    try:
        entries  = db.get_memory(project_id=project_id, limit=10000)
        failures = db.search_failures("", limit=10000)
        buckets  = {1: 0, 3: 0, 5: 0, 7: 0, 10: 0}
        for e in entries:
            s = e.get("importance_score", 1)
            b = min(buckets.keys(), key=lambda x: abs(x - s))
            buckets[b] += 1
        return {"total_entries": len(entries),
                "total_failures": len(failures),
                "score_distribution": buckets}
    except Exception as e:
        print(f"{_MODULE} Stats error: {e}")
        return {}


if __name__ == "__main__":
    import os, tempfile, importlib, sys
    tmp = tempfile.mktemp(suffix=".db")
    os.environ["GRIDMASTER_DB"] = tmp
    if "database" in sys.modules:
        importlib.reload(sys.modules["database"])
    import database as _db
    _db.init_db()
    pid = _db.create_project("MM Test", "memory_manager self-test")
    tid = _db.create_task(pid, "Test memory", priority=5)
    remember(tid, "Started", importance=SCORE_LOG, project_id=pid)
    remember(tid, "Worker ran Flask route", importance=SCORE_RESULT, project_id=pid)
    remember_failure(tid, "ImportError: flask", cause="missing dep",
                     fix="pip install flask", tags=["python"], project_id=pid)
    extract_knowledge("flask_health", "@app.route('/health')\ndef h(): return jsonify({})",
                      summary="Flask health pattern", tags=["flask"])
    ctx = build_context(tid, project_id=pid, keyword="flask")
    assert ctx["memories"], "Expected memories"
    stats = memory_stats(project_id=pid)
    assert stats["total_entries"] >= 2
    _db.close_db()
    os.remove(tmp)
    print(f"{_MODULE} Self-test passed.")
