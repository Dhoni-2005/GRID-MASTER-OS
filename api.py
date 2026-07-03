"""
interface/api.py — Grid Master OS Phase 5
Flask REST API adapter over common.py.
No business logic — delegates to common.validate() + common.run().

Routes:
    POST /run              — submit a task through the full kernel lifecycle
    GET  /status           — system health check
    GET  /commands         — list registry commands
    POST /command          — execute a registry command
    GET  /projects         — list active projects
    GET  /nodes            — list registered nodes
    GET  /agents           — list active agents
    GET  /memory/stats     — memory statistics
    GET  /db/stats         — database statistics
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, request, jsonify

from interface        import common
from interface.auth   import check_auth
from interface.command_registry import dispatch, list_commands
import database as _db
import node_registry as _nr


def create_app() -> Flask:
    """
    Create and configure the Flask application.
    Returns the app instance — does not call app.run().
    """
    app = Flask(__name__, static_folder=None)
    app.config["JSON_SORT_KEYS"] = False

    # ── Auth middleware ───────────────────────────────────────
    @app.before_request
    def _auth_check():
        if not check_auth(request):
            return jsonify({"status": "error",
                            "error": "Unauthorized"}), 401

    # ── POST /run ─────────────────────────────────────────────
    @app.route("/run", methods=["POST"])
    def run_task_route():
        """Submit a task through the full kernel lifecycle."""
        body = request.get_json(force=True, silent=True) or {}

        args_dict, error = common.validate(
            title          = body.get("title", ""),
            input_data     = body.get("input_data", ""),
            project_id     = body.get("project_id"),
            priority       = body.get("priority", 5),
            max_iterations = body.get("max_iterations", 100),
        )
        if error:
            return jsonify({"status": "error", "error": error}), 400

        result = common.run(**args_dict)
        status_code = 200 if result.get("status") != "error" else 500
        # Kernel-returned errors that are expected (e.g. invalid project_id)
        # still use 200 — they are valid kernel responses, not transport errors.
        # Only a kernel *exception* (caught in common.run) warrants 500.
        if result.get("error") and "does not exist" in (result.get("error") or ""):
            status_code = 400
        return jsonify(result), status_code

    # ── GET /status ───────────────────────────────────────────
    @app.route("/status", methods=["GET"])
    def status_route():
        """System health check — returns db stats and node counts."""
        try:
            stats = _db.db_stats()
            nodes = _db.list_all_nodes()
            online = sum(1 for n in nodes if n.get("status") == "online")
            return jsonify({
                "status":       "ok",
                "version":      "1.0.0",
                "phase":        "Phase 5 — Interface Layer",
                "database":     stats,
                "nodes_total":  len(nodes),
                "nodes_online": online,
            }), 200
        except Exception as e:
            return jsonify({"status": "error", "error": str(e)}), 500

    # ── GET /commands ─────────────────────────────────────────
    @app.route("/commands", methods=["GET"])
    def commands_route():
        """List all registry commands."""
        return jsonify({"status": "ok", "commands": list_commands()}), 200

    # ── POST /command ─────────────────────────────────────────
    @app.route("/command", methods=["POST"])
    def command_route():
        """Execute a registry command by name."""
        body    = request.get_json(force=True, silent=True) or {}
        command = body.get("command", "")
        if not command:
            return jsonify({"status": "error",
                            "error": "command field is required"}), 400
        kwargs = {k: v for k, v in body.items() if k != "command"}
        result = dispatch(command, **kwargs)
        code   = 200 if result.get("status") == "ok" else 400
        return jsonify(result), code

    # ── GET /projects ─────────────────────────────────────────
    @app.route("/projects", methods=["GET"])
    def projects_route():
        try:
            projects = _db.list_projects(status="active")
            return jsonify({"status": "ok", "projects": projects}), 200
        except Exception as e:
            return jsonify({"status": "error", "error": str(e)}), 500

    # ── GET /nodes ────────────────────────────────────────────
    @app.route("/nodes", methods=["GET"])
    def nodes_route():
        try:
            nodes = _db.list_all_nodes()
            return jsonify({"status": "ok", "nodes": nodes}), 200
        except Exception as e:
            return jsonify({"status": "error", "error": str(e)}), 500

    # ── GET /agents ───────────────────────────────────────────
    @app.route("/agents", methods=["GET"])
    def agents_route():
        try:
            agents = _db.get_active_agents()
            return jsonify({"status": "ok", "agents": agents}), 200
        except Exception as e:
            return jsonify({"status": "error", "error": str(e)}), 500

    # ── GET /memory/stats ─────────────────────────────────────
    @app.route("/memory/stats", methods=["GET"])
    def memory_stats_route():
        try:
            pid   = request.args.get("project_id", type=int)
            stats = _db.memory_stats_counts(project_id=pid)
            return jsonify({"status": "ok", "memory": stats}), 200
        except Exception as e:
            return jsonify({"status": "error", "error": str(e)}), 500

    # ── GET /db/stats ─────────────────────────────────────────
    @app.route("/db/stats", methods=["GET"])
    def db_stats_route():
        try:
            return jsonify({"status": "ok", "stats": _db.db_stats()}), 200
        except Exception as e:
            return jsonify({"status": "error", "error": str(e)}), 500

    # ── Error handlers ────────────────────────────────────────
    @app.errorhandler(400)
    def bad_request(e):
        return jsonify({"status": "error", "error": str(e)}), 400

    @app.errorhandler(404)
    def not_found(e):
        return jsonify({"status": "error",
                        "error": f"Route not found: {request.path}"}), 404

    @app.errorhandler(405)
    def method_not_allowed(e):
        return jsonify({"status": "error",
                        "error": f"Method {request.method} not allowed"}), 405

    @app.errorhandler(500)
    def internal_error(e):
        return jsonify({"status": "error",
                        "error": "Internal server error"}), 500

    return app


# ── RUNNER ────────────────────────────────────────────────────
if __name__ == "__main__":
    import os as _os
    port = int(_os.environ.get("GRIDMASTER_PORT", 8000))
    app  = create_app()
    print(f"[API] Grid Master OS API starting on http://0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
