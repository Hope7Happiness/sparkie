"""Meeting workspaces: durable store keyed by workspace_id, not the platform's meeting id.

Zoom UUIDs, Meet ids, or Teams ids are external references that resolve to one
workspace; agent and artifact logic never touches platform identifiers.
"""
import json
import sqlite3
import time
from uuid import uuid4

from .contracts import TranscriptEvent

SCHEMA = """
CREATE TABLE IF NOT EXISTS meetings(
  workspace_id TEXT PRIMARY KEY,
  external_kind TEXT NOT NULL,
  external_id TEXT NOT NULL,
  title TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'live',
  generation INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL,
  UNIQUE(external_kind, external_id));
CREATE TABLE IF NOT EXISTS transcript_events(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  meeting_id TEXT NOT NULL,
  event_id TEXT,
  speaker TEXT,
  text TEXT NOT NULL,
  timestamp_ms INTEGER NOT NULL DEFAULT 0,
  is_final INTEGER NOT NULL DEFAULT 1,
  source TEXT NOT NULL DEFAULT 'human');
CREATE TABLE IF NOT EXISTS tasks(
  task_id TEXT PRIMARY KEY,
  meeting_id TEXT NOT NULL,
  instruction TEXT NOT NULL,
  artifact_title TEXT,
  status TEXT NOT NULL DEFAULT 'queued',
  created_from_transcript_id INTEGER,
  result TEXT,
  error TEXT,
  created_at REAL NOT NULL,
  finished_at REAL);
CREATE TABLE IF NOT EXISTS artifacts(
  artifact_id TEXT PRIMARY KEY,
  meeting_id TEXT NOT NULL,
  task_id TEXT,
  type TEXT NOT NULL DEFAULT 'report',
  title TEXT NOT NULL DEFAULT '',
  summary TEXT NOT NULL DEFAULT '',
  content_json TEXT,
  content_url TEXT,
  status TEXT NOT NULL DEFAULT 'ready',
  created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS meeting_state(
  meeting_id TEXT PRIMARY KEY,
  active_artifact_id TEXT,
  current_topic TEXT);
"""


def _row(cursor):
    columns = [column[0] for column in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


class WorkspaceStore:
    """Synchronous SQLite store; single-writer is fine for the MVP event loop."""

    def __init__(self, path):
        self.db = sqlite3.connect(str(path))
        self.db.executescript(SCHEMA)
        # Existing workspace databases retain their meeting IDs and history.
        if 'generation' not in {row[1] for row in self.db.execute('PRAGMA table_info(meetings)')}:
            self.db.execute('ALTER TABLE meetings ADD COLUMN generation INTEGER NOT NULL DEFAULT 0')
            self.db.commit()
        if 'artifact_title' not in {row[1] for row in self.db.execute('PRAGMA table_info(tasks)')}:
            self.db.execute('ALTER TABLE tasks ADD COLUMN artifact_title TEXT')
            self.db.commit()

    def close(self):
        self.db.close()

    # -- meetings / resolution -------------------------------------------------
    def create_workspace(self, external_kind, external_id, title=""):
        workspace_id = f"ws_{uuid4().hex[:8]}"
        self.db.execute(
            "INSERT INTO meetings(workspace_id, external_kind, external_id, title, status, created_at)"
            " VALUES(?,?,?,?,'live',?)",
            (workspace_id, external_kind, external_id, title, time.time()))
        self.db.commit()
        return workspace_id

    def resolve(self, external_kind, external_id):
        row = self.db.execute(
            "SELECT workspace_id FROM meetings WHERE external_kind=? AND external_id=?",
            (external_kind, external_id)).fetchone()
        return row[0] if row else None

    def resolve_or_create(self, external_kind, external_id, title=""):
        return self.resolve(external_kind, external_id) or \
            self.create_workspace(external_kind, external_id, title)

    def get_workspace(self, workspace_id):
        rows = _row(self.db.execute("SELECT * FROM meetings WHERE workspace_id=?", (workspace_id,)))
        return rows[0] if rows else None

    def list_workspaces(self):
        rows = _row(self.db.execute(
            "SELECT m.*, "
            " (SELECT COUNT(*) FROM transcript_events t WHERE t.meeting_id=m.workspace_id) AS transcript_count,"
            " (SELECT COUNT(*) FROM tasks k WHERE k.meeting_id=m.workspace_id) AS task_count,"
            " (SELECT COUNT(*) FROM artifacts a WHERE a.meeting_id=m.workspace_id) AS artifact_count"
            " FROM meetings m ORDER BY created_at DESC"))
        return rows

    def set_status(self, workspace_id, status):
        self.db.execute("UPDATE meetings SET status=? WHERE workspace_id=?", (status, workspace_id))
        self.db.commit()

    def reset(self, workspace_id):
        """A new session reusing an external meeting id starts a fresh canvas."""
        with self.db:
            for table in ('transcript_events', 'tasks', 'artifacts', 'meeting_state'):
                self.db.execute(f"DELETE FROM {table} WHERE meeting_id=?", (workspace_id,))
            self.db.execute("UPDATE meetings SET status='live', generation=generation+1 WHERE workspace_id=?",
                            (workspace_id,))

    def generation(self, workspace_id):
        row = self.db.execute('SELECT generation FROM meetings WHERE workspace_id=?', (workspace_id,)).fetchone()
        return row[0] if row else None

    # -- transcript -------------------------------------------------------------
    def append_transcript(self, workspace_id, event: TranscriptEvent):
        cursor = self.db.execute(
            "INSERT INTO transcript_events(meeting_id, event_id, speaker, text, timestamp_ms, is_final, source)"
            " VALUES(?,?,?,?,?,?,?)",
            (workspace_id, event.event_id, event.speaker, event.text,
             event.timestamp_ms, int(event.is_final), event.source))
        self.db.commit()
        return cursor.lastrowid

    def transcript(self, workspace_id):
        return _row(self.db.execute(
            "SELECT * FROM transcript_events WHERE meeting_id=? ORDER BY id", (workspace_id,)))

    # -- tasks ------------------------------------------------------------------
    def create_task(self, workspace_id, instruction, transcript_id=None):
        task_id = f"t_{uuid4().hex[:10]}"
        self.db.execute(
            "INSERT INTO tasks(task_id, meeting_id, instruction, status, created_from_transcript_id, created_at)"
            " VALUES(?,?,?,'queued',?,?)",
            (task_id, workspace_id, instruction, transcript_id, time.time()))
        self.db.commit()
        return task_id

    def finish_task(self, task_id, status, result=None, error=None):
        self.db.execute(
            "UPDATE tasks SET status=?, result=?, error=?, finished_at=? WHERE task_id=?",
            (status, result, error, time.time(), task_id))
        self.db.commit()

    def upsert_task(self, workspace_id, task_id, instruction, status, result=None, error=None,
                    artifact_title=None):
        """Mirror an external session's task lifecycle; task_id is owned by the caller."""
        finished = time.time() if status in ('completed', 'failed', 'cancelled') else None
        self.db.execute(
            "INSERT INTO tasks(task_id, meeting_id, instruction, status, result, error, created_at, finished_at, artifact_title)"
            " VALUES(?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(task_id) DO UPDATE SET status=excluded.status,"
            " artifact_title=COALESCE(excluded.artifact_title, artifact_title),"
            " result=COALESCE(excluded.result, result), error=COALESCE(excluded.error, error),"
            " finished_at=COALESCE(excluded.finished_at, finished_at)",
            (task_id, workspace_id, instruction or task_id, status, result, error,
             time.time(), finished, artifact_title))
        self.db.commit()

    # -- artifacts ---------------------------------------------------------------
    def create_artifact(self, workspace_id, task_id=None, type="report", title="",
                        summary="", content=None, content_url=None, status="ready"):
        artifact_id = f"art_{uuid4().hex[:10]}"
        self.db.execute(
            "INSERT INTO artifacts(artifact_id, meeting_id, task_id, type, title, summary,"
            " content_json, content_url, status, created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (artifact_id, workspace_id, task_id, type, title, summary,
             json.dumps(content, ensure_ascii=False) if content is not None else None,
             content_url, status, time.time()))
        self.db.commit()
        return artifact_id

    def get_artifact(self, artifact_id):
        rows = _row(self.db.execute("SELECT * FROM artifacts WHERE artifact_id=?", (artifact_id,)))
        if not rows:
            return None
        artifact = rows[0]
        if artifact["content_json"]:
            artifact["content"] = json.loads(artifact["content_json"])
        artifact.pop("content_json", None)
        return artifact

    def latest_artifact(self, workspace_id, status="ready"):
        row = self.db.execute(
            "SELECT artifact_id FROM artifacts WHERE meeting_id=? AND status=?"
            " ORDER BY created_at DESC, artifact_id DESC LIMIT 1",
            (workspace_id, status)).fetchone()
        return row[0] if row else None

    def artifact_catalog(self, workspace_id):
        return _row(self.db.execute(
            "SELECT artifact_id, task_id, type, title, summary, status FROM artifacts"
            " WHERE meeting_id=? ORDER BY created_at DESC, artifact_id DESC LIMIT 50",
            (workspace_id,)))

    # -- shared UI state -----------------------------------------------------------
    def set_active_artifact(self, workspace_id, artifact_id):
        self.db.execute(
            "INSERT INTO meeting_state(meeting_id, active_artifact_id) VALUES(?,?)"
            " ON CONFLICT(meeting_id) DO UPDATE SET active_artifact_id=excluded.active_artifact_id",
            (workspace_id, artifact_id))
        self.db.commit()

    def get_state(self, workspace_id):
        rows = _row(self.db.execute("SELECT * FROM meeting_state WHERE meeting_id=?", (workspace_id,)))
        return rows[0] if rows else {"meeting_id": workspace_id, "active_artifact_id": None, "current_topic": None}

    # -- snapshots for GET /workspaces/:id -------------------------------------------
    def snapshot(self, workspace_id):
        workspace = self.get_workspace(workspace_id)
        if not workspace:
            return None
        artifacts = _row(self.db.execute(
            "SELECT * FROM artifacts WHERE meeting_id=? ORDER BY created_at", (workspace_id,)))
        for artifact in artifacts:
            if artifact["content_json"]:
                artifact["content"] = json.loads(artifact["content_json"])
            artifact.pop("content_json", None)
        return {"workspace": workspace,
                "transcript": self.transcript(workspace_id),
                "tasks": _row(self.db.execute(
                    "SELECT * FROM tasks WHERE meeting_id=? ORDER BY created_at", (workspace_id,))),
                "artifacts": artifacts,
                "state": self.get_state(workspace_id)}
