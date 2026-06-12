"""
database.py — Grid Master OS Kernel v1.1
Unified database layer. One schema, all future divisions.
Wirth Lean: one system, many capabilities.

Improvements in v1.1:
- Centralized _exec() / _query() helpers eliminate duplicated
  get_db() calls across caller modules.
- All multi-step writes wrapped in explicit transactions with
  rollback on failure.
- Thread-local connection pool with lazy initialisation.
- Improved error messages with module context prefix.
- Safer init_db using executescript inside a transaction.
- Tags helper consolidated; never leaks raw lists into SQL.
"""
import sqlite3
import datetime
import json
import os
import threading

DB_PATH = os.environ.get("GRIDMASTER_DB", "gridmaster.db")
_local  = threading.local()
_MODULE = "[DB]"


# ── CONNECTION ────────────────────────────────────────────────

def get_db() -> sqlite3.Connection:
    """Per-thread connection — safe under concurrent use."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA synchronous=NORMAL")
        _local.conn = conn
    return conn


def close_db() -> None:
    """Explicitly close the thread-local connection. Call before os.remove()."""
    conn = getattr(_local, "conn", None)
    if conn:
        try:
            conn.close()
        except Exception:
            pass
        _local.conn = None


# ── INTERNAL HELPERS ─────────────────────────────────────────
# These replace raw get_db() calls in caller modules.
# They ensure every write is wrapped in a transaction.

def _exec(sql: str, args: tuple = ()) -> int:
    """
    Execute a single write statement inside a transaction.
    Returns lastrowid. Rolls back on any error.
    """
    conn = get_db()
    try:
        with conn:          # context manager: commits or rolls back
            cur = conn.execute(sql, args)
        return cur.lastrowid
    except sqlite3.Error as e:
        raise RuntimeError(f"{_MODULE} Write failed: {e}\nSQL: {sql}") from e


def _exec_many(statements: list[tuple]) -> None:
    """
    Execute multiple (sql, args) pairs as a single atomic transaction.
    All succeed or all roll back.
    """
    conn = get_db()
    try:
        with conn:
            for sql, args in statements:
                conn.execute(sql, args)
    except sqlite3.Error as e:
        raise RuntimeError(f"{_MODULE} Multi-write failed: {e}") from e


def _query(sql: str, args: tuple = ()) -> list[dict]:
    """Execute a read query and return list of dicts."""
    try:
        rows = get_db().execute(sql, args).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.Error as e:
        raise RuntimeError(f"{_MODULE} Query failed: {e}\nSQL: {sql}") from e


def _query_one(sql: str, args: tuple = ()) -> dict | None:
    """Execute a read query and return first row or None."""
    try:
        row = get_db().execute(sql, args).fetchone()
        return dict(row) if row else None
    except sqlite3.Error as e:
        raise RuntimeError(f"{_MODULE} Query failed: {e}\nSQL: {sql}") from e


def _scalar(sql: str, args: tuple = ()) -> int:
    """Return a single integer scalar (e.g. COUNT)."""
    try:
        row = get_db().execute(sql, args).fetchone()
        return row[0] if row else 0
    except sqlite3.Error as e:
        raise RuntimeError(f"{_MODULE} Scalar failed: {e}") from e


# ── HELPERS ───────────────────────────────────────────────────

def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat()


def _tags(tags) -> str:
    """Safely serialise a tag list to JSON string."""
    if isinstance(tags, list):
        return json.dumps(tags)
    if isinstance(tags, str):
        return tags
    return "[]"


# ── SCHEMA INIT ───────────────────────────────────────────────

def init_db() -> None:
    """Create all tables and indexes. Safe to call on every startup."""
    conn = get_db()
    try:
        with conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS projects (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    name        TEXT    NOT NULL,
                    description TEXT    DEFAULT '',
                    status      TEXT    NOT NULL DEFAULT 'active',
                    created_at  TEXT    NOT NULL,
                    updated_at  TEXT    NOT NULL
                );

                CREATE TABLE IF NOT EXISTS tasks (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id     INTEGER REFERENCES projects(id) ON DELETE SET NULL,
                    parent_task_id INTEGER REFERENCES tasks(id)    ON DELETE SET NULL,
                    title          TEXT    NOT NULL,
                    status         TEXT    NOT NULL DEFAULT 'pending',
                    priority       INTEGER NOT NULL DEFAULT 5,
                    input          TEXT    DEFAULT '',
                    output         TEXT    DEFAULT '',
                    created_at     TEXT    NOT NULL,
                    completed_at   TEXT    DEFAULT NULL
                );

                CREATE TABLE IF NOT EXISTS memory_entries (
                    id               INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id       INTEGER REFERENCES projects(id) ON DELETE SET NULL,
                    task_id          INTEGER REFERENCES tasks(id)    ON DELETE SET NULL,
                    content          TEXT    NOT NULL,
                    summary          TEXT    DEFAULT '',
                    entry_type       TEXT    NOT NULL DEFAULT 'log',
                    tags             TEXT    DEFAULT '[]',
                    importance_score INTEGER NOT NULL DEFAULT 1,
                    created_at       TEXT    NOT NULL
                );

                CREATE TABLE IF NOT EXISTS failure_memory (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
                    task_id    INTEGER REFERENCES tasks(id)    ON DELETE SET NULL,
                    problem    TEXT    NOT NULL,
                    cause      TEXT    DEFAULT '',
                    fix        TEXT    DEFAULT '',
                    tags       TEXT    DEFAULT '[]',
                    created_at TEXT    NOT NULL
                );

                CREATE TABLE IF NOT EXISTS agent_notes (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id    INTEGER REFERENCES tasks(id) ON DELETE CASCADE,
                    agent_role TEXT    NOT NULL,
                    note       TEXT    NOT NULL,
                    created_at TEXT    NOT NULL
                );

                CREATE TABLE IF NOT EXISTS knowledge_base (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    topic      TEXT    NOT NULL,
                    content    TEXT    NOT NULL,
                    summary    TEXT    DEFAULT '',
                    source     TEXT    DEFAULT '',
                    tags       TEXT    DEFAULT '[]',
                    created_at TEXT    NOT NULL
                );

                CREATE TABLE IF NOT EXISTS agent_registry (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_name   TEXT    NOT NULL UNIQUE,
                    agent_role   TEXT    NOT NULL,
                    status       TEXT    NOT NULL DEFAULT 'active',
                    capabilities TEXT    DEFAULT '[]',
                    created_at   TEXT    NOT NULL,
                    updated_at   TEXT    NOT NULL
                );

                CREATE TABLE IF NOT EXISTS node_registry (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    node_id        TEXT    NOT NULL UNIQUE,
                    node_name      TEXT    NOT NULL,
                    platform       TEXT    NOT NULL DEFAULT 'unknown',
                    role           TEXT    NOT NULL DEFAULT 'worker',
                    url            TEXT    DEFAULT '',
                    status         TEXT    NOT NULL DEFAULT 'offline',
                    last_heartbeat TEXT    DEFAULT NULL,
                    capabilities   TEXT    DEFAULT '[]',
                    created_at     TEXT    NOT NULL,
                    updated_at     TEXT    NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_tasks_project
                    ON tasks(project_id);
                CREATE INDEX IF NOT EXISTS idx_tasks_parent
                    ON tasks(parent_task_id);
                CREATE INDEX IF NOT EXISTS idx_tasks_status
                    ON tasks(status);
                CREATE INDEX IF NOT EXISTS idx_memory_task
                    ON memory_entries(task_id);
                CREATE INDEX IF NOT EXISTS idx_memory_project
                    ON memory_entries(project_id);
                CREATE INDEX IF NOT EXISTS idx_memory_score
                    ON memory_entries(importance_score DESC);
                CREATE INDEX IF NOT EXISTS idx_failures_project
                    ON failure_memory(project_id);
                CREATE INDEX IF NOT EXISTS idx_notes_task
                    ON agent_notes(task_id);
                CREATE INDEX IF NOT EXISTS idx_kb_topic
                    ON knowledge_base(topic);
                CREATE INDEX IF NOT EXISTS idx_nodes_status
                    ON node_registry(status);
                CREATE INDEX IF NOT EXISTS idx_nodes_role
                    ON node_registry(role);
            """)
    except sqlite3.Error as e:
        raise RuntimeError(f"{_MODULE} Schema init failed: {e}") from e
    print(f"{_MODULE} Initialized: {DB_PATH}")


# ── PROJECTS ──────────────────────────────────────────────────

def create_project(name: str, description: str = "") -> int:
    now = _now()
    return _exec(
        "INSERT INTO projects (name,description,status,created_at,updated_at) VALUES (?,?,?,?,?)",
        (name, description, "active", now, now),
    )


def get_project(project_id: int) -> dict | None:
    return _query_one("SELECT * FROM projects WHERE id=?", (project_id,))


def list_projects(status: str = "active") -> list[dict]:
    return _query(
        "SELECT * FROM projects WHERE status=? ORDER BY created_at DESC", (status,)
    )


def update_project_status(project_id: int, status: str) -> None:
    _exec(
        "UPDATE projects SET status=?,updated_at=? WHERE id=?",
        (status, _now(), project_id),
    )


# ── TASKS ─────────────────────────────────────────────────────

def create_task(project_id: int, title: str, input_data: str = "",
                priority: int = 5, parent_task_id: int | None = None) -> int:
    now = _now()
    return _exec(
        "INSERT INTO tasks "
        "(project_id,parent_task_id,title,status,priority,input,created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (project_id, parent_task_id, title, "pending", priority, input_data, now),
    )


def update_task_status(task_id: int, status: str, output: str = "") -> None:
    now = _now()
    if status == "completed":
        _exec(
            "UPDATE tasks SET status=?,output=?,completed_at=? WHERE id=?",
            (status, output, now, task_id),
        )
    else:
        _exec(
            "UPDATE tasks SET status=?,output=? WHERE id=?",
            (status, output, task_id),
        )


def get_task(task_id: int) -> dict | None:
    return _query_one("SELECT * FROM tasks WHERE id=?", (task_id,))


def get_subtasks(parent_task_id: int) -> list[dict]:
    return _query(
        "SELECT * FROM tasks WHERE parent_task_id=? ORDER BY priority DESC",
        (parent_task_id,),
    )


def list_tasks(project_id: int | None = None,
               status: str | None = None) -> list[dict]:
    query = "SELECT * FROM tasks WHERE 1=1"
    args: list = []
    if project_id is not None:
        query += " AND project_id=?"
        args.append(project_id)
    if status:
        query += " AND status=?"
        args.append(status)
    query += " ORDER BY priority DESC, created_at ASC"
    return _query(query, tuple(args))


# ── MEMORY ENTRIES ────────────────────────────────────────────

def store_memory(task_id: int, content: str, entry_type: str = "log",
                 tags: list | None = None, importance_score: int = 1,
                 project_id: int | None = None, summary: str = "") -> int:
    return _exec(
        "INSERT INTO memory_entries "
        "(project_id,task_id,content,summary,entry_type,tags,importance_score,created_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (project_id, task_id, content, summary, entry_type,
         _tags(tags), importance_score, _now()),
    )


def get_memory(task_id: int | None = None, project_id: int | None = None,
               min_score: int = 1, limit: int = 20) -> list[dict]:
    query = "SELECT * FROM memory_entries WHERE importance_score >= ?"
    args: list = [min_score]
    if task_id is not None:
        query += " AND task_id=?"
        args.append(task_id)
    if project_id is not None:
        query += " AND project_id=?"
        args.append(project_id)
    query += " ORDER BY importance_score DESC, created_at DESC LIMIT ?"
    args.append(limit)
    return _query(query, tuple(args))


def search_memory(keyword: str, project_id: int | None = None,
                  min_score: int = 1, limit: int = 10) -> list[dict]:
    like  = f"%{keyword}%"
    query = ("SELECT * FROM memory_entries "
             "WHERE (content LIKE ? OR summary LIKE ? OR tags LIKE ?) "
             "AND importance_score >= ?")
    args: list = [like, like, like, min_score]
    if project_id is not None:
        query += " AND project_id=?"
        args.append(project_id)
    query += " ORDER BY importance_score DESC LIMIT ?"
    args.append(limit)
    return _query(query, tuple(args))


# ── FAILURE MEMORY ────────────────────────────────────────────

def store_failure(task_id: int, problem: str, cause: str = "",
                  fix: str = "", tags: list | None = None,
                  project_id: int | None = None) -> int:
    return _exec(
        "INSERT INTO failure_memory "
        "(project_id,task_id,problem,cause,fix,tags,created_at) VALUES (?,?,?,?,?,?,?)",
        (project_id, task_id, problem, cause, fix, _tags(tags), _now()),
    )


def search_failures(keyword: str, limit: int = 5) -> list[dict]:
    like = f"%{keyword}%"
    return _query(
        "SELECT * FROM failure_memory "
        "WHERE problem LIKE ? OR cause LIKE ? OR tags LIKE ? "
        "ORDER BY created_at DESC LIMIT ?",
        (like, like, like, limit),
    )


# ── AGENT NOTES ───────────────────────────────────────────────

def write_note(task_id: int, agent_role: str, note: str) -> int:
    return _exec(
        "INSERT INTO agent_notes (task_id,agent_role,note,created_at) VALUES (?,?,?,?)",
        (task_id, agent_role, note, _now()),
    )


def get_notes(task_id: int, agent_role: str | None = None) -> list[dict]:
    query = "SELECT * FROM agent_notes WHERE task_id=?"
    args: list = [task_id]
    if agent_role:
        query += " AND agent_role=?"
        args.append(agent_role)
    query += " ORDER BY created_at ASC"
    return _query(query, tuple(args))


# ── KNOWLEDGE BASE ────────────────────────────────────────────

def store_knowledge(topic: str, content: str, summary: str = "",
                    source: str = "", tags: list | None = None) -> int:
    return _exec(
        "INSERT INTO knowledge_base (topic,content,summary,source,tags,created_at) "
        "VALUES (?,?,?,?,?,?)",
        (topic, content, summary, source, _tags(tags), _now()),
    )


def search_knowledge(query_str: str, limit: int = 5) -> list[dict]:
    like = f"%{query_str}%"
    return _query(
        "SELECT * FROM knowledge_base "
        "WHERE topic LIKE ? OR content LIKE ? OR tags LIKE ? "
        "ORDER BY created_at DESC LIMIT ?",
        (like, like, like, limit),
    )


# ── AGENT REGISTRY ────────────────────────────────────────────

def register_agent(agent_name: str, agent_role: str,
                   capabilities: list | None = None) -> int:
    now = _now()
    return _exec(
        "INSERT INTO agent_registry "
        "(agent_name,agent_role,status,capabilities,created_at,updated_at) "
        "VALUES (?,?,?,?,?,?) "
        "ON CONFLICT(agent_name) DO UPDATE SET "
        "status='active', updated_at=excluded.updated_at",
        (agent_name, agent_role, "active", _tags(capabilities), now, now),
    )


def get_active_agents(role: str | None = None) -> list[dict]:
    query = "SELECT * FROM agent_registry WHERE status='active'"
    args: list = []
    if role:
        query += " AND agent_role=?"
        args.append(role)
    return _query(query, tuple(args))


# ── NODE REGISTRY ─────────────────────────────────────────────

def register_node(node_id: str, node_name: str, platform: str = "unknown",
                  role: str = "worker", url: str = "",
                  capabilities: list | None = None) -> int:
    now = _now()
    return _exec(
        "INSERT INTO node_registry "
        "(node_id,node_name,platform,role,url,status,capabilities,created_at,updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(node_id) DO UPDATE SET "
        "node_name=excluded.node_name, platform=excluded.platform, "
        "role=excluded.role, url=excluded.url, "
        "status='online', updated_at=excluded.updated_at",
        (node_id, node_name, platform, role, url, "online",
         _tags(capabilities), now, now),
    )


def update_heartbeat(node_id: str) -> None:
    now = _now()
    _exec(
        "UPDATE node_registry SET last_heartbeat=?,status='online',updated_at=? WHERE node_id=?",
        (now, now, node_id),
    )


def set_node_status(node_id: str, status: str) -> None:
    _exec(
        "UPDATE node_registry SET status=?,updated_at=? WHERE node_id=?",
        (status, _now(), node_id),
    )


def get_online_nodes(role: str | None = None) -> list[dict]:
    query = "SELECT * FROM node_registry WHERE status='online'"
    args: list = []
    if role:
        query += " AND role=?"
        args.append(role)
    return _query(query, tuple(args))


def get_node(node_id: str) -> dict | None:
    return _query_one("SELECT * FROM node_registry WHERE node_id=?", (node_id,))


def list_all_nodes() -> list[dict]:
    return _query("SELECT * FROM node_registry ORDER BY role, node_name")


# ── ATOMIC MULTI-STEP HELPERS ─────────────────────────────────
# These are the transaction-safe composite writes used by
# grid_master.py to avoid partial state updates.

def complete_task_atomic(task_id: int, output: str,
                         node_id: str | None,
                         memory_content: str,
                         project_id: int | None,
                         lesson: str = "") -> None:
    """
    Atomically:
      - Mark task completed
      - Release node (if provided)
      - Store memory entry
      - Optionally store lesson memory
    All succeed or all roll back.
    """
    now = _now()
    statements: list[tuple] = [
        (
            "UPDATE tasks SET status='completed',output=?,completed_at=? WHERE id=?",
            (output, now, task_id),
        ),
        (
            "INSERT INTO memory_entries "
            "(project_id,task_id,content,summary,entry_type,tags,importance_score,created_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (project_id, task_id, memory_content, "", "result",
             "[]", 3, now),
        ),
    ]
    if node_id:
        statements.append((
            "UPDATE node_registry SET status='online',updated_at=? WHERE node_id=?",
            (now, node_id),
        ))
    if lesson:
        statements.append((
            "INSERT INTO memory_entries "
            "(project_id,task_id,content,summary,entry_type,tags,importance_score,created_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (project_id, task_id, lesson, lesson[:100], "lesson", "[]", 7, now),
        ))
    _exec_many(statements)


def fail_task_atomic(task_id: int, status: str, output: str,
                     node_id: str | None, problem: str,
                     cause: str, fix: str, tags: list,
                     project_id: int | None) -> None:
    """
    Atomically:
      - Mark task failed/abandoned
      - Release node (if provided)
      - Store failure_memory record
      - Store high-importance memory entry
    All succeed or all roll back.
    """
    now = _now()
    statements: list[tuple] = [
        (
            "UPDATE tasks SET status=?,output=? WHERE id=?",
            (status, output, task_id),
        ),
        (
            "INSERT INTO failure_memory "
            "(project_id,task_id,problem,cause,fix,tags,created_at) VALUES (?,?,?,?,?,?,?)",
            (project_id, task_id, problem, cause, fix, _tags(tags), now),
        ),
        (
            "INSERT INTO memory_entries "
            "(project_id,task_id,content,summary,entry_type,tags,importance_score,created_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (project_id, task_id,
             f"FAILURE: {problem}. Cause: {cause}. Fix: {fix}",
             f"Failure: {problem[:80]}", "failure", _tags(tags), 10, now),
        ),
    ]
    if node_id:
        statements.append((
            "UPDATE node_registry SET status='online',updated_at=? WHERE node_id=?",
            (now, node_id),
        ))
    _exec_many(statements)


# ── DB STATS ──────────────────────────────────────────────────

def db_stats() -> dict:
    tables = ["projects", "tasks", "memory_entries",
              "failure_memory", "knowledge_base",
              "agent_registry", "node_registry"]
    stats = {t: _scalar(f"SELECT COUNT(*) FROM {t}") for t in tables}
    stats["db_path"]    = DB_PATH
    stats["db_size_kb"] = (
        round(os.path.getsize(DB_PATH) / 1024, 1)
        if os.path.exists(DB_PATH) else 0
    )
    return stats


# ── SELF-TEST ─────────────────────────────────────────────────
if __name__ == "__main__":
    import tempfile, os as _os
    tmp = tempfile.mktemp(suffix=".db")
    _os.environ["GRIDMASTER_DB"] = tmp
    import importlib, sys
    # Reload so DB_PATH picks up the env var
    if "database" in sys.modules:
        importlib.reload(sys.modules["database"])
    import database as _db
    _db.init_db()
    pid = _db.create_project("Test", "Self-test project")
    tid = _db.create_task(pid, "Test task", priority=5)
    _db.write_note(tid, "coordinator", "Boot note")
    _db.store_memory(tid, "Hello memory", importance_score=5, project_id=pid)
    _db.store_failure(tid, "Test failure", cause="test", fix="test fix",
                      tags=["test"], project_id=pid)
    _db.store_knowledge("test_topic", "test content", tags=["test"])
    _db.register_agent("coordinator", "coordinator", ["route"])
    _db.register_node("n01", "Node 01", platform="local", role="worker")
    _db.update_heartbeat("n01")
    _db.complete_task_atomic(tid, "done", "n01", "Completed.", pid, "Always test atomically.")
    _db.close_db()
    _os.remove(tmp)
    print(f"[DB] Self-test passed.")
