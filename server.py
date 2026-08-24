#!/usr/bin/env python3
"""Real-time Hermes Dashboard — PWA backend with WebSocket push."""

import asyncio
import json
import os
import sqlite3
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

HERMES_HOME = "/opt/data"
REFRESH_INTERVAL = 3  # seconds

app = FastAPI(title="Hermes Real-Time Dashboard")

# Store connected WebSocket clients
connected_clients: set[WebSocket] = set()

# ── Agent event tracking ─────────────────────────────────────────────
# Track previous agent states for change detection
_prev_session_states: dict[str, dict] = {}
_agent_events: list[dict] = []
_MAX_EVENTS = 200


def _record_event(kind: str, session_id: str, source: str | None,
                  title: str | None, detail: str = ""):
    """Add an event to the rolling event log."""
    global _agent_events
    _agent_events.append({
        "kind": kind,
        "session_id": session_id,
        "source": source or "?",
        "title": (title or session_id[:16])[:60],
        "detail": detail,
        "timestamp": time.time(),
    })
    # Trim to max
    if len(_agent_events) > _MAX_EVENTS:
        _agent_events = _agent_events[-_MAX_EVENTS:]


def detect_agent_events(roots: list) -> list[dict]:
    """Compare current agent tree with previous state, log changes, return new events."""
    global _prev_session_states
    now = time.time()
    new_events = []

    # Build current snapshot of session states
    current_states: dict[str, dict] = {}
    for root in roots:
        s = root.get("session", {})
        sid = s.get("id", "")
        if not sid:
            continue
        is_active = s.get("last_activity_seconds_ago", 999) < 120
        has_work = (s.get("tool_call_count") or 0) > 3
        current_states[sid] = {
            "active": is_active,
            "has_work": has_work,
            "messages": s.get("message_count") or 0,
            "tools": s.get("tool_call_count") or 0,
            "source": s.get("source"),
            "title": s.get("title"),
        }
        # Also track children
        for c in root.get("child_sessions", []):
            cid = c.get("id", "")
            if not cid:
                continue
            c_active = c.get("last_activity_seconds_ago", 999) < 120
            c_work = (c.get("tool_call_count") or 0) > 2
            current_states[cid] = {
                "active": c_active,
                "has_work": c_work,
                "messages": c.get("message_count") or 0,
                "tools": c.get("tool_call_count") or 0,
                "source": c.get("source"),
                "title": c.get("title"),
            }

    # Compare with previous state
    all_ids = set(current_states.keys()) | set(_prev_session_states.keys())

    for sid in all_ids:
        cur = current_states.get(sid)
        prev = _prev_session_states.get(sid)

        if cur is None and prev is not None:
            # Session disappeared (ended)
            new_events.append(_record_event(
                "agent_ended", sid, prev.get("source"),
                prev.get("title"), "Session ended"
            ))
        elif cur is not None and prev is None:
            # New session appeared
            new_events.append(_record_event(
                "agent_started", sid, cur.get("source"),
                cur.get("title"), "New agent session"
            ))
        elif cur and prev:
            # Check activity transition
            if cur["active"] and not prev["active"]:
                new_events.append(_record_event(
                    "agent_working", sid, cur.get("source"),
                    cur.get("title"), "Agent started working"
                ))
            elif not cur["active"] and prev["active"]:
                new_events.append(_record_event(
                    "agent_idle", sid, cur.get("source"),
                    cur.get("title"), "Agent went idle"
                ))
            elif cur["active"] and prev["active"]:
                # Check for tool use milestones
                cur_tools = cur.get("tools", 0)
                prev_tools = prev.get("tools", 0)
                if cur_tools - prev_tools >= 5:
                    new_events.append(_record_event(
                        "tool_milestone", sid, cur.get("source"),
                        cur.get("title"),
                        f"+{cur_tools - prev_tools} tool calls"
                    ))

    _prev_session_states = current_states
    return new_events


def get_events(limit: int = 30) -> list[dict]:
    """Return the most recent agent events."""
    return list(reversed(_agent_events[-limit:]))


# ── Data collectors ──────────────────────────────────────────────────

def read_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _profile_gateway_state(name: str) -> dict:
    if name == "default":
        path = f"{HERMES_HOME}/gateway_state.json"
    else:
        path = f"{HERMES_HOME}/profiles/{name}/gateway_state.json"
    return read_json(path) or {}


def get_gateway_status():
    data = read_json(f"{HERMES_HOME}/gateway_state.json") or {}
    if data.get("gateway_state") == "running":
        data["state"] = "running"
    else:
        data["state"] = "unknown"
    # Default has telegram.enabled: false (avoids polling fight). Live Telegram
    # is the cpp-developer gateway — overlay so status.proyectos is not a false alarm.
    plats = dict(data.get("platforms") or {})
    tg = plats.get("telegram") or {}
    if tg.get("state") != "connected":
        cpp_tg = ((_profile_gateway_state("cpp-developer").get("platforms") or {}).get("telegram") or {})
        if cpp_tg.get("state") == "connected":
            plats["telegram"] = {
                **cpp_tg,
                "delegated_to": "cpp-developer",
            }
        elif tg.get("error_code") == "missing_credentials":
            plats["telegram"] = {
                **tg,
                "state": "disabled",
                "error_message": "off (delegado a cpp-developer)",
            }
    data["platforms"] = plats
    return data


def get_all_gateways():
    """Report status for all Hermes profile gateways."""
    profile_gateways = {}

    # Default profile gateway
    gw_path = f"{HERMES_HOME}/gateway_state.json"
    if os.path.isfile(gw_path):
        gw = read_json(gw_path) or {}
        if gw.get("gateway_state") == "running":
            profile_gateways["default"] = {
                "state": "running",
                "pid": gw.get("pid"),
                "platforms": gw.get("platforms", {}),
                "start_time": gw.get("start_time"),
            }
        else:
            profile_gateways["default"] = {"state": "unknown"}

    # Profile-specific gateways — check via process list
    profile_names = [
        "tester-stack", "ux-ui-designer", "petbook-frontend", "job-hunter",
        "cpp-developer", "ml-learner", "scriptable-dev", "unreal-mentor", "vanlife-optimizer",
    ]
    for name in profile_names:
        pid = _find_profile_gateway_pid(name)
        st = _profile_gateway_state(name)
        live_pid = pid or (st.get("pid") if st.get("gateway_state") == "running" else None)
        profile_gateways[name] = {
            "state": "running" if live_pid else "down",
            "pid": live_pid,
            "platforms": st.get("platforms") or {},
        }

    # Also read watchdog status if available
    watchdog = read_json(f"{HERMES_HOME}/.hermes/gateway-watchdog-status.json") or {}
    return {"profiles": profile_gateways, "watchdog": watchdog.get("watchdog", False)}


def _find_profile_gateway_pid(profile: str) -> int | None:
    """Find PID of a profile gateway by scanning /proc."""
    import re
    markers = [
        f"hermes gateway run -p {profile}",
        f"hermes -p {profile} gateway run",
        f"hermes gateway run --replace --accept-hooks -p {profile}",
    ]
    try:
        for pid_dir in os.listdir("/proc"):
            if not pid_dir.isdigit():
                continue
            try:
                with open(f"/proc/{pid_dir}/cmdline", "rb") as f:
                    raw = f.read()
                cmdline = raw.replace(b"\x00", b" ").decode("utf-8", errors="replace")
                for m in markers:
                    if m in cmdline:
                        return int(pid_dir)
            except (IOError, OSError, ValueError):
                continue
    except OSError:
        pass
    return None


def get_processes():
    """Tracked Hermes processes (from processes.json)."""
    procs = read_json(f"{HERMES_HOME}/processes.json") or []
    active = []
    for p in procs:
        pid = p.get("pid")
        alive = False
        if pid:
            try:
                os.kill(pid, 0)
                alive = True
            except OSError:
                pass
        if alive:
            started = p.get("started_at", 0)
            active.append({
                "pid": pid,
                "command": p.get("command", "")[:120],
                "cwd": p.get("cwd", ""),
                "started_at": started,
                "uptime_seconds": time.time() - started if started else 0,
                "alive": True,
            })
    return active


def get_kanban_tasks():
    """Active tasks from kanban.db (incl. sub-agents)."""
    db = f"{HERMES_HOME}/kanban.db"
    if not os.path.isfile(db):
        return []
    try:
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        # Active = in_progress or pending (not completed/cancelled)
        rows = conn.execute("""
            SELECT id, title, status, assignee, priority, worker_pid,
                   created_at, started_at, last_heartbeat_at,
                   consecutive_failures, last_failure_error,
                   current_run_id, goal_mode, max_runtime_seconds
            FROM tasks
            WHERE status NOT IN ('completed', 'cancelled', 'failed')
            ORDER BY
                CASE status
                    WHEN 'in_progress' THEN 0
                    WHEN 'pending' THEN 1
                    WHEN 'blocked' THEN 2
                    ELSE 3
                END,
                created_at DESC
            LIMIT 50
        """).fetchall()
        tasks = []
        for r in rows:
            task = dict(r)
            # Check if worker is alive
            wp = task.get("worker_pid")
            if wp:
                try:
                    os.kill(wp, 0)
                    task["worker_alive"] = True
                except OSError:
                    task["worker_alive"] = False
            else:
                task["worker_alive"] = None

            # Timeline
            for field in ["created_at", "started_at", "last_heartbeat_at"]:
                v = task.get(field)
                if v and isinstance(v, (int, float)):
                    task[field] = v
            tasks.append(task)

        # Also get parent-child links
        links = conn.execute("""
            SELECT parent_id, child_id FROM task_links
        """).fetchall()
        task_links = [dict(l) for l in links]

        # Get recent runs
        runs = conn.execute("""
            SELECT id, task_id, profile, step_key, status, worker_pid,
                   started_at, ended_at, summary
            FROM task_runs
            WHERE status IN ('running', 'pending')
            ORDER BY started_at DESC
            LIMIT 20
        """).fetchall()
        active_runs = [dict(r) for r in runs]

        conn.close()
        return {"tasks": tasks, "links": task_links, "runs": active_runs}
    except Exception as e:
        return {"tasks": [], "links": [], "runs": [], "error": str(e)}


def get_sessions():
    """Active sessions from state.db."""
    db = f"{HERMES_HOME}/state.db"
    if not os.path.isfile(db):
        return []
    try:
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT id, source, user_id, model, title, started_at,
                   message_count, tool_call_count,
                   input_tokens, output_tokens, estimated_cost_usd,
                   ended_at, end_reason, archived
            FROM sessions
            WHERE ended_at IS NULL AND archived = 0
            ORDER BY started_at DESC
            LIMIT 20
        """).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        return []


def get_cron_jobs():
    """Cron jobs from the Hermes cron state (read from file/scheduler)."""
    cron_file = f"{HERMES_HOME}/cron/jobs.json"
    cron_data = {"jobs": [], "updated_at": None}
    if os.path.isfile(cron_file):
        try:
            with open(cron_file) as f:
                cron_data = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    
    # Add output file timestamps to each job
    cron_out = f"{HERMES_HOME}/.hermes/cron/output"
    if os.path.isdir(cron_out):
        for job in cron_data.get("jobs", []):
            jid = job.get("id", "")
            if jid:
                out_path = os.path.join(cron_out, jid)
                if os.path.isfile(out_path):
                    job["output_mtime"] = os.path.getmtime(out_path)
                    job["output_size"] = os.path.getsize(out_path)

    return cron_data


def get_agent_tree():
    """Build a tree of active sessions → tasks → sub-tasks for agent visibility."""
    state_db = f"{HERMES_HOME}/state.db"
    kanban_db = f"{HERMES_HOME}/kanban.db"
    tree = {"roots": [], "orphans": [], "recent_tool_calls": []}

    # ── 1. Load active sessions with rich details ──
    sessions = {}
    last_activity = {}  # session_id -> timestamp of last message
    
    if os.path.isfile(state_db):
        try:
            conn = sqlite3.connect(state_db)
            conn.row_factory = sqlite3.Row
            
            # Fetch active sessions
            rows = conn.execute("""
                SELECT id, parent_session_id, source, user_id, model,
                       title, started_at, message_count, tool_call_count,
                       input_tokens, output_tokens, estimated_cost_usd,
                       ended_at, archived
                FROM sessions
                WHERE ended_at IS NULL AND archived = 0
                ORDER BY started_at DESC
                LIMIT 200
            """).fetchall()
            for r in rows:
                sessions[r["id"]] = dict(r)

            # Fetch last activity time per session
            act_rows = conn.execute("""
                SELECT session_id, MAX(timestamp) as last_ts
                FROM messages
                WHERE session_id IN ({})
                GROUP BY session_id
            """.format(','.join('?' for _ in sessions.keys())),
                list(sessions.keys())
            ).fetchall()
            for r in act_rows:
                last_activity[r["session_id"]] = r["last_ts"]

            # Fetch recent tool calls (last 10 globally)
            tool_rows = conn.execute("""
                SELECT session_id, role, tool_name, timestamp,
                       content
                FROM messages
                WHERE tool_name IS NOT NULL
                ORDER BY timestamp DESC
                LIMIT 10
            """).fetchall()
            tree["recent_tool_calls"] = [
                {
                    "session_id": r["session_id"],
                    "role": r["role"],
                    "tool_name": r["tool_name"],
                    "timestamp": r["timestamp"],
                }
                for r in tool_rows
            ]

            conn.close()
        except Exception as e:
            return {"error": str(e)}

    # Compute uptime and last activity for each session
    now = time.time()
    for sid, s in sessions.items():
        s["age_seconds"] = now - s.get("started_at", now) if s.get("started_at") else 0
        s["last_activity_seconds_ago"] = now - last_activity.get(sid, s.get("started_at", now))
        s["total_tokens"] = (s.get("input_tokens") or 0) + (s.get("output_tokens") or 0)

    # ── 2. Load kanban tasks linked to sessions ──
    task_map = {}
    if os.path.isfile(kanban_db):
        try:
            conn = sqlite3.connect(kanban_db)
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT id, title, status, assignee, priority, worker_pid,
                       created_at, started_at, last_heartbeat_at,
                       session_id, goal_mode, consecutive_failures,
                       last_failure_error
                FROM tasks
                WHERE session_id IS NOT NULL
                  AND status NOT IN ('completed', 'cancelled', 'failed')
                ORDER BY created_at DESC
                LIMIT 100
            """).fetchall()
            for r in rows:
                task = dict(r)
                wp = task.get("worker_pid")
                if wp:
                    try:
                        os.kill(wp, 0)
                        task["worker_alive"] = True
                    except OSError:
                        task["worker_alive"] = False
                else:
                    task["worker_alive"] = None
                sid = task.pop("session_id", None)
                if sid:
                    task_map.setdefault(sid, []).append(task)

            links = conn.execute("""
                SELECT parent_id, child_id FROM task_links
            """).fetchall()
            task_links = [dict(l) for l in links]

            all_tasks_rows = conn.execute("""
                SELECT id, title, status, assignee, priority, worker_pid,
                       created_at, started_at, last_heartbeat_at,
                       session_id, goal_mode, consecutive_failures
                FROM tasks
                WHERE status NOT IN ('completed', 'cancelled', 'failed')
                ORDER BY created_at DESC
                LIMIT 200
            """).fetchall()
            all_tasks = {}
            for r in all_tasks_rows:
                t = dict(r)
                wp = t.get("worker_pid")
                if wp:
                    try:
                        os.kill(wp, 0)
                        t["worker_alive"] = True
                    except OSError:
                        t["worker_alive"] = False
                else:
                    t["worker_alive"] = None
                all_tasks[t["id"]] = t

            tree["task_links"] = task_links
            session_task_ids = set()
            for tl in task_map.values():
                for t in tl:
                    session_task_ids.add(t["id"])
            tree["all_tasks"] = {k: v for k, v in all_tasks.items()
                                 if k not in session_task_ids}
            conn.close()
        except Exception as e:
            tree["task_error"] = str(e)

    # ── 3. Build parent → children map ──
    parent_set = set(sessions.keys())
    child_map = {}
    root_ids = set()

    for sid, s in sessions.items():
        pid = s.get("parent_session_id")
        if pid and pid in parent_set:
            child_map.setdefault(pid, []).append(s)
        else:
            root_ids.add(sid)

    # ── 4. Assemble roots with children and enriched details ──
    def attach_tasks(session_id):
        return task_map.get(session_id, [])

    roots = []
    for rid in sorted(root_ids, key=lambda x: sessions[x].get("last_activity_seconds_ago", 99999)):
        s = sessions[rid]
        children = child_map.get(rid, [])
        children.sort(key=lambda x: x.get("last_activity_seconds_ago", 99999))
        roots.append({
            "session": s,
            "tasks": attach_tasks(rid),
            "child_sessions": [
                {**c, "tasks": attach_tasks(c["id"])}
                for c in children[:30]
            ],
        })

    tree["roots"] = roots[:50]
    orphan_tasks = []
    for sid, tl in task_map.items():
        if sid not in parent_set:
            orphan_tasks.extend(tl)
    tree["orphan_tasks"] = orphan_tasks[:20]

    return tree


def get_active_workers():
    """Scan system for active Python worker processes and gateway children."""
    workers = []
    try:
        hermes_pids = set()
        for p in Path("/proc").iterdir():
            if not p.name.isdigit():
                continue
            try:
                stat = p / "stat"
                if not stat.exists():
                    continue
                with open(stat) as f:
                    parts = f.read().split(")")
                    if len(parts) < 2:
                        continue
                    comm = parts[0].split("(")[-1] if "(" in parts[0] else ""
                    rest = parts[1].strip().split()
                    if len(rest) < 2:
                        continue
                    ppid = int(rest[1])
                    pid = int(p.name)

                cmdline = ""
                try:
                    with open(p / "cmdline", "rb") as f:
                        cmdline = f.read().decode("utf-8", errors="replace").replace("\0", " ").strip()
                except OSError:
                    pass

                # Only track Python/node processes related to hermes
                if not cmdline or not ("python3" in cmdline.lower() or "node" in cmdline.lower()):
                    continue
                if "grep" in cmdline or "start-" in cmdline or "spa-server" in cmdline:
                    continue

                # Get RSS
                rss = 0
                try:
                    with open(p / "status") as f:
                        for line in f:
                            if line.startswith("VmRSS:"):
                                rss = int(line.split()[1])
                                break
                except OSError:
                    pass

                workers.append({
                    "pid": pid,
                    "ppid": ppid,
                    "command": cmdline[:150],
                    "rss_kb": rss,
                    "cpu_percent": 0,
                })
            except (OSError, ValueError, IndexError):
                continue

        workers.sort(key=lambda x: x["rss_kb"], reverse=True)
        return workers[:30]
    except Exception as e:
        return [{"error": str(e)}]


def get_system_stats():
    """Basic system resource info."""
    try:
        # CPU load
        load = os.getloadavg()
        # Memory
        mem = {}
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    mem["total_kb"] = int(line.split()[1])
                elif line.startswith("MemAvailable:"):
                    mem["available_kb"] = int(line.split()[1])
                elif line.startswith("MemFree:"):
                    mem["free_kb"] = int(line.split()[1])

        # Process count
        proc_count = len(os.listdir("/proc")) - 2  # minus . and ..

        # Uptime
        with open("/proc/uptime") as f:
            uptime_seconds = float(f.read().split()[0])

        return {
            "load_1m": round(load[0], 2),
            "load_5m": round(load[1], 2),
            "load_15m": round(load[2], 2),
            "memory": mem,
            "process_count": proc_count,
            "uptime_seconds": uptime_seconds,
            "timestamp": time.time(),
        }
    except Exception as e:
        return {"error": str(e)}


def check_socats():
    """Check socat port forwards via public IP."""
    gateway = "148.230.118.249"
    forwards = {
        "80 (HTTP)": 80,
        "443 (HTTPS)": 443,
        "32768 (Dashboard)": 32768,
        "32770 (WebUI)": 32770,
        "3333 (RT Dash)": 3333,
    }
    results = {}
    all_ok = True
    for name, port in forwards.items():
        try:
            import socket
            s = socket.create_connection((gateway, port), timeout=1)
            s.close()
            results[name] = "up"
        except (OSError, Exception):
            results[name] = "down"
            all_ok = False
    return {
        "forwards": results,
        "all_up": all_ok,
        "gateway": gateway,
        "checked_at": time.time(),
    }


def collect_snapshot():
    """Full dashboard state snapshot."""
    gateway = get_gateway_status()
    now = time.time()

    # Get agent tree first so we can detect events
    agent_tree = get_agent_tree()
    new_events = detect_agent_events(agent_tree.get("roots", []))

    all_gateways = get_all_gateways()

    snapshot = {
        "timestamp": now,
        "datetime": datetime.fromtimestamp(now, tz=timezone.utc).isoformat(),
        "gateway": {
            "state": gateway.get("state", "unknown"),
            "pid": gateway.get("pid"),
            "active_agents": gateway.get("active_agents", 0),
            "platforms": gateway.get("platforms", {}),
            "start_time": gateway.get("start_time"),
            "uptime_seconds": now - gateway.get("start_time", now) if gateway.get("start_time") else 0,
            "profiles": all_gateways.get("profiles", {}),
            "watchdog": all_gateways.get("watchdog", False),
        },
        "socats": check_socats(),
        "processes": get_processes(),
        "kanban": get_kanban_tasks(),
        "sessions": get_sessions(),
        "agent_tree": agent_tree,
        "workers": get_active_workers(),
        "events": new_events,  # only new events since last poll
        "event_history": get_events(50),  # full recent history
        "cron_files": get_cron_jobs(),
        "system": get_system_stats(),
    }
    return snapshot


# ── FastAPI routes ───────────────────────────────────────────────────

@app.get("/api/snapshot")
async def api_snapshot():
    return collect_snapshot()


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_clients.add(websocket)
    try:
        while True:
            # Wait for client ping or timeout
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=REFRESH_INTERVAL)
                if data == "ping":
                    await websocket.send_json({"type": "pong"})
            except asyncio.TimeoutError:
                # Timeout = send snapshot
                snapshot = collect_snapshot()
                await websocket.send_json({"type": "snapshot", "data": snapshot})
    except WebSocketDisconnect:
        pass
    finally:
        connected_clients.discard(websocket)


# Serve the PWA files
app.mount("/", StaticFiles(directory=os.path.dirname(__file__), html=True), name="static")


# ── Main ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("DASHBOARD_PORT", 3333))
    host = os.environ.get("DASHBOARD_HOST", "0.0.0.0")
    print(f"[dash] Starting Hermes Real-Time Dashboard on {host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="warning")
