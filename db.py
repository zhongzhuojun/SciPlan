from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime
from pathlib import Path


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._init()

    def _init(self):
        with self.lock, self.conn:
            self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS board (id TEXT PRIMARY KEY, name TEXT UNIQUE NOT NULL, color TEXT, sort INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS project (id TEXT PRIMARY KEY, board_id TEXT NOT NULL, name TEXT NOT NULL, kind TEXT, deadline TEXT, journal TEXT, sort INTEGER DEFAULT 0, weight REAL DEFAULT 1, created_at TEXT);
            CREATE TABLE IF NOT EXISTS workstream (id TEXT PRIMARY KEY, project_id TEXT NOT NULL, name TEXT NOT NULL, status TEXT DEFAULT 'not_started', sort INTEGER DEFAULT 0, color TEXT, created_at TEXT);
            CREATE TABLE IF NOT EXISTS task (
                id TEXT PRIMARY KEY, title TEXT NOT NULL, raw_text TEXT, board_id TEXT, project_id TEXT,
                priority INTEGER DEFAULT 3, priority_reason TEXT, due TEXT, est_hours REAL DEFAULT 1,
                need_focus INTEGER DEFAULT 0, status TEXT DEFAULT 'todo', blocked_by TEXT,
                ai_confidence REAL DEFAULT 0.5, created_at TEXT, updated_at TEXT, done_at TEXT
            );
            CREATE TABLE IF NOT EXISTS correction (id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT, field TEXT, ai_value TEXT, user_value TEXT, created_at TEXT);
            CREATE TABLE IF NOT EXISTS setting (key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE IF NOT EXISTS dashboard_card (
                id TEXT PRIMARY KEY, title TEXT NOT NULL, kind TEXT NOT NULL,
                target_date TEXT, base_date TEXT, value TEXT, subtitle TEXT,
                color TEXT DEFAULT '#6F83A8', sort INTEGER DEFAULT 0, created_at TEXT
            );
            """)
            # Older prototypes used random board ids. Consolidate them into the
            # stable ids so an existing local database does not show duplicate
            # navigation entries after an upgrade.
            boards = [("paper", "论文", "#EA695D", 0), ("research", "课题", "#5E9BEA", 1), ("grant", "标书", "#EF9F27", 2), ("misc", "杂事", "#B4B2A9", 3)]
            for stable_id, name, color, sort in boards:
                old = [r[0] for r in self.conn.execute("SELECT id FROM board WHERE name=?", (name,)).fetchall()]
                if old and stable_id not in old:
                    self.conn.execute("UPDATE board SET id=? WHERE id=?", (stable_id, old[0]))
                    old = [stable_id] + old[1:]
                for duplicate in old:
                    if duplicate != stable_id:
                        self.conn.execute("UPDATE task SET board_id=? WHERE board_id=?", (stable_id, duplicate))
                        self.conn.execute("DELETE FROM board WHERE id=?", (duplicate,))
            self.conn.executemany("INSERT OR IGNORE INTO board(id,name,color,sort) VALUES(?,?,?,?)", boards)
            self.conn.execute("UPDATE task SET est_hours=1 WHERE est_hours IS NULL")
            self._migrate_columns()
            self._seed_workstreams()

    def _migrate_columns(self):
        cols = {r[1] for r in self.conn.execute("PRAGMA table_info(task)").fetchall()}
        additions = {
            "workstream_id": "TEXT", "time_state": "TEXT DEFAULT 'unknown'", "time_window": "TEXT",
            "prerequisite": "TEXT", "purpose": "TEXT", "success_criteria": "TEXT", "dependencies": "TEXT",
            "notes": "TEXT",
        }
        for name, spec in additions.items():
            if name not in cols:
                self.conn.execute(f"ALTER TABLE task ADD COLUMN {name} {spec}")
        pcols = {r[1] for r in self.conn.execute("PRAGMA table_info(project)").fetchall()}
        had_project_sort = "sort" in pcols
        had_project_weight = "weight" in pcols
        for name, spec in {"objective": "TEXT", "current_block": "TEXT", "status": "TEXT DEFAULT 'active'", "sort": "INTEGER DEFAULT 0", "weight": "REAL DEFAULT 1"}.items():
            if name not in pcols:
                self.conn.execute(f"ALTER TABLE project ADD COLUMN {name} {spec}")
        if not had_project_sort:
            self.conn.execute("UPDATE project SET sort=rowid-1")
        if not had_project_weight:
            self.conn.execute("UPDATE project SET weight=1")
        self.conn.execute("UPDATE task SET time_state='dated' WHERE due IS NOT NULL AND (time_state IS NULL OR time_state='unknown')")

    def _seed_workstreams(self):
        projects = self.conn.execute("SELECT id,kind FROM project").fetchall()
        for project_id, kind in projects:
            names = ["写作线", "合作线"] if kind == "paper" else ["结构线", "机制线", "表型线", "写作线", "合作线"]
            existing_names = {r[0] for r in self.conn.execute("SELECT name FROM workstream WHERE project_id=?", (project_id,)).fetchall()}
            next_sort = self.conn.execute("SELECT COALESCE(MAX(sort),-1)+1 FROM workstream WHERE project_id=?", (project_id,)).fetchone()[0]
            for idx, name in enumerate(names):
                if name in existing_names: continue
                self.conn.execute("INSERT INTO workstream(id,project_id,name,status,sort,color,created_at) VALUES(?,?,?,?,?,?,?)", (str(uuid.uuid4()), project_id, name, "not_started", next_sort, "#6F83A8", datetime.now().isoformat(timespec="seconds")))
                next_sort += 1

    def _rows(self, sql, args=()):
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    def boards(self):
        return self._rows("SELECT * FROM board ORDER BY sort")

    def add_board(self, name: str, color: str = "#7A8FB8"):
        board_id = str(uuid.uuid4())
        with self.lock, self.conn:
            sort = self.conn.execute("SELECT COALESCE(MAX(sort), -1) + 1 FROM board").fetchone()[0]
            self.conn.execute("INSERT INTO board(id,name,color,sort) VALUES(?,?,?,?)", (board_id, name.strip() or "新模块", color, sort))
        return self._rows("SELECT * FROM board WHERE id=?", (board_id,))[0]

    def update_board(self, board_id: str, changes: dict):
        allowed = {"name", "color", "sort"}; changes = {k: v for k, v in changes.items() if k in allowed}
        if not changes: return
        with self.lock, self.conn:
            self.conn.execute(f"UPDATE board SET {', '.join(k+'=?' for k in changes)} WHERE id=?", (*changes.values(), board_id))

    def archive_board(self, board_id: str):
        with self.lock, self.conn:
            self.conn.execute("UPDATE board SET sort=-1 WHERE id=?", (board_id,))

    def cards(self):
        return self._rows("SELECT * FROM dashboard_card ORDER BY sort, created_at")

    def add_card(self, card: dict):
        card_id = card.get("id") or str(uuid.uuid4()); now = datetime.now().isoformat(timespec="seconds")
        with self.lock, self.conn:
            sort = self.conn.execute("SELECT COALESCE(MAX(sort), -1) + 1 FROM dashboard_card").fetchone()[0]
            self.conn.execute("""INSERT INTO dashboard_card(id,title,kind,target_date,base_date,value,subtitle,color,sort,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?)""", (card_id, card.get("title", "新卡片"), card.get("kind", "countdown"), card.get("target_date"), card.get("base_date"), card.get("value"), card.get("subtitle", ""), card.get("color", "#6F83A8"), sort, now))
        return self._rows("SELECT * FROM dashboard_card WHERE id=?", (card_id,))[0]

    def update_card(self, card_id: str, changes: dict):
        allowed = {"title", "kind", "target_date", "base_date", "value", "subtitle", "color", "sort"}; changes = {k: v for k, v in changes.items() if k in allowed}
        if not changes: return
        with self.lock, self.conn:
            self.conn.execute(f"UPDATE dashboard_card SET {', '.join(k+'=?' for k in changes)} WHERE id=?", (*changes.values(), card_id))

    def delete_card(self, card_id: str):
        with self.lock, self.conn:
            self.conn.execute("DELETE FROM dashboard_card WHERE id=?", (card_id,))

    def projects(self):
        return self._rows("SELECT * FROM project WHERE COALESCE(status,'active') != 'archived' ORDER BY sort, name")

    def workstreams(self, project_id=None):
        if project_id:
            return self._rows("SELECT * FROM workstream WHERE project_id=? ORDER BY sort,name", (project_id,))
        return self._rows("SELECT * FROM workstream ORDER BY project_id,sort,name")

    def project_summaries(self):
        projects = self.projects(); tasks = [t for t in self.tasks(True) if t.get("status") != "deleted"]; streams = self.workstreams()
        result = []
        for p in projects:
            mine = [t for t in tasks if t.get("project_id") == p["id"]]
            total_tasks = len(mine)
            done_tasks = sum(1 for t in mine if t.get("status") == "done")
            progress = round(done_tasks * 100 / total_tasks) if total_tasks else 0
            result.append({**p, "tasks": total_tasks, "done_tasks": done_tasks, "progress_percent": progress,
                           "completed_hours": round(sum(float(t.get("est_hours") or 1) for t in mine if t.get("status") == "done"), 1),
                           "remaining_hours": round(sum(float(t.get("est_hours") or 1) for t in mine if t.get("status") != "done"), 1),
                           "status_counts": {s: sum(1 for t in mine if t.get("status") == s) for s in ("todo", "doing", "waiting", "done")},
                           "workstreams": [dict(w, task_count=sum(1 for t in mine if t.get("workstream_id") == w["id"])) for w in streams if w["project_id"] == p["id"]],
                           "missing_count": sum(1 for t in mine if not t.get("purpose") or not t.get("success_criteria") or not t.get("prerequisite"))})
        return result

    def add_project(self, project: dict):
        pid = project.get("id") or str(uuid.uuid4()); now = datetime.now().isoformat(timespec="seconds")
        with self.lock, self.conn:
            board_id = project.get("board_id") or "research"
            sort = project.get("sort") if project.get("sort") is not None else self.conn.execute("SELECT COALESCE(MAX(sort),-1)+1 FROM project").fetchone()[0]
            self.conn.execute("INSERT INTO project(id,board_id,name,kind,deadline,journal,sort,weight,objective,current_block,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (pid, board_id, project.get("name", "新课题"), project.get("kind", "research"), project.get("deadline"), project.get("journal"), sort, float(project.get("weight", 1) or 1), project.get("objective"), project.get("current_block"), project.get("status", "active"), now))
        self._seed_workstreams()
        return self._rows("SELECT * FROM project WHERE id=?", (pid,))[0]

    def update_project(self, project_id: str, changes: dict):
        allowed = {"name", "board_id", "kind", "deadline", "journal", "objective", "current_block", "status", "sort", "weight"}; changes = {k:v for k,v in changes.items() if k in allowed}
        if not changes: return
        with self.lock, self.conn:
            self.conn.execute(f"UPDATE project SET {', '.join(k+'=?' for k in changes)} WHERE id=?", (*changes.values(), project_id))

    def delete_project(self, project_id: str):
        """Permanently remove a project and its workstreams/tasks."""
        with self.lock, self.conn:
            self.conn.execute("DELETE FROM task WHERE project_id=?", (project_id,))
            self.conn.execute("DELETE FROM workstream WHERE project_id=?", (project_id,))
            self.conn.execute("DELETE FROM project WHERE id=?", (project_id,))

    def add_workstream(self, project_id: str, stream: dict):
        wid = stream.get("id") or str(uuid.uuid4()); now = datetime.now().isoformat(timespec="seconds")
        with self.lock, self.conn:
            sort = self.conn.execute("SELECT COALESCE(MAX(sort),-1)+1 FROM workstream WHERE project_id=?", (project_id,)).fetchone()[0]
            self.conn.execute("INSERT INTO workstream(id,project_id,name,status,sort,color,created_at) VALUES(?,?,?,?,?,?,?)", (wid, project_id, stream.get("name", "新实验线"), stream.get("status", "not_started"), sort, stream.get("color", "#6F83A8"), now))
        return self._rows("SELECT * FROM workstream WHERE id=?", (wid,))[0]

    def update_workstream(self, stream_id: str, changes: dict):
        allowed = {"name", "status", "sort", "color"}; changes = {k:v for k,v in changes.items() if k in allowed}
        if not changes: return
        with self.lock, self.conn:
            self.conn.execute(f"UPDATE workstream SET {', '.join(k+'=?' for k in changes)} WHERE id=?", (*changes.values(), stream_id))

    def tasks(self, include_done=True):
        where = "" if include_done else "WHERE t.status != 'done'"
        return self._rows(f"""SELECT t.*, b.name AS board_name, b.color AS board_color, p.name AS project_name, w.name AS workstream_name
            FROM task t LEFT JOIN board b ON b.id=t.board_id LEFT JOIN project p ON p.id=t.project_id LEFT JOIN workstream w ON w.id=t.workstream_id
            {where} ORDER BY CASE WHEN t.status='waiting' THEN 1 ELSE 0 END, t.due IS NULL, t.due, t.priority, t.created_at DESC""")

    def add_task(self, task: dict):
        now = datetime.now().isoformat(timespec="seconds")
        task_id = task.get("id") or str(uuid.uuid4())
        with self.lock, self.conn:
            self.conn.execute("""INSERT INTO task(id,title,raw_text,board_id,project_id,workstream_id,priority,priority_reason,due,time_state,time_window,prerequisite,purpose,success_criteria,dependencies,notes,est_hours,need_focus,status,blocked_by,ai_confidence,created_at,updated_at)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (task_id, task.get("title", "未命名任务"), task.get("raw"), task.get("board_id", "misc"), task.get("project_id"), task.get("workstream_id"), int(task.get("priority", 3)), task.get("reason", ""), task.get("due"), task.get("time_state", "dated" if task.get("due") else "unknown"), task.get("time_window"), task.get("prerequisite"), task.get("purpose"), task.get("success_criteria"), task.get("dependencies"), task.get("notes"), float(task.get("est_hours", 1)), int(bool(task.get("need_focus"))), task.get("status", "todo"), task.get("blocked_by"), float(task.get("confidence", .5)), now, now))
        return self._rows("SELECT * FROM task WHERE id=?", (task_id,))[0]

    def update_task(self, task_id: str, changes: dict):
        allowed = {"title", "board_id", "project_id", "workstream_id", "priority", "due", "time_state", "time_window", "prerequisite", "purpose", "success_criteria", "dependencies", "notes", "est_hours", "need_focus", "status", "blocked_by", "priority_reason", "done_at"}
        changes = {k: v for k, v in changes.items() if k in allowed}
        if "status" in changes and changes["status"] == "done":
            changes["done_at"] = datetime.now().isoformat(timespec="seconds")
        if not changes:
            return
        changes["updated_at"] = datetime.now().isoformat(timespec="seconds")
        cols = ", ".join(f"{k}=?" for k in changes)
        with self.lock, self.conn:
            self.conn.execute(f"UPDATE task SET {cols} WHERE id=?", (*changes.values(), task_id))

    def delete_task(self, task_id: str):
        with self.lock, self.conn:
            self.conn.execute("UPDATE task SET status='deleted', updated_at=? WHERE id=?", (datetime.now().isoformat(timespec="seconds"), task_id))

    def add_correction(self, task_id, field, ai_value, user_value):
        with self.lock, self.conn:
            self.conn.execute("INSERT INTO correction(task_id,field,ai_value,user_value,created_at) VALUES(?,?,?,?,?)", (task_id, field, str(ai_value), str(user_value), datetime.now().isoformat(timespec="seconds")))

    def export_json(self):
        return {"boards": self.boards(), "projects": self.projects(), "workstreams": self.workstreams(), "tasks": self.tasks(), "cards": self.cards(), "exported_at": datetime.now().isoformat(timespec="seconds")}

    def import_json(self, payload):
        for task in payload.get("tasks", []):
            task = dict(task); task.pop("board_name", None); task.pop("board_color", None); task.pop("project_name", None)
            self.add_task(task)
        for card in payload.get("cards", []):
            self.add_card(card)
