"""
scheduler/db.py

SQLite database layer for cluster state persistence.

Tables:
- nodes: registered nodes and their metadata
- node_profiles: hardware benchmark results
- jobs: job submissions with timestamps
- job_results: job execution results with timestamps
"""

import sqlite3
import json
import os
from datetime import datetime
from typing import Optional, Dict, List, Any
from contextlib import contextmanager

from shared.timeutils import to_iso, utc_now

DATABASE_PATH = os.getenv("SCHEDULER_DB", "scheduler.db")


def get_db_connection():
    """Get a connection to the SQLite database."""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def get_db():
    """Context manager for database connections."""
    conn = get_db_connection()
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


def _table_columns(cursor, table: str) -> set:
    """Column names of an existing table."""
    cursor.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cursor.fetchall()}


def _migrate_schema(cursor) -> None:
    """
    Bring an existing database up to the current schema.

    CREATE TABLE IF NOT EXISTS does nothing to a table that already exists,
    so columns added after a database was first created have to be applied
    explicitly. Each step is guarded, making init_db() safe to re-run.
    """
    columns = _table_columns(cursor, "jobs")

    if "run_id" not in columns:
        cursor.execute("ALTER TABLE jobs ADD COLUMN run_id TEXT")

    # Declared requirements, stored per job so results can be broken down by
    # workload type rather than averaged into a single meaningless figure.
    for column, definition in (
        ("workload_type", "TEXT"),
        ("cpu_request", "INTEGER"),
        ("memory_mb", "INTEGER"),
        ("requires_gpu", "INTEGER"),
        ("job_size", "INTEGER"),
    ):
        if column not in columns:
            cursor.execute(f"ALTER TABLE jobs ADD COLUMN {column} {definition}")


def init_db():
    """Initialize the database schema."""
    with get_db() as conn:
        cursor = conn.cursor()

        # Nodes table: registration info and heartbeat tracking
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS nodes (
                node_id TEXT PRIMARY KEY,
                hostname TEXT NOT NULL,
                agent_url TEXT NOT NULL,
                registered_at TIMESTAMP NOT NULL,
                last_heartbeat TIMESTAMP,
                current_load REAL DEFAULT 0.0
            )
        """)

        # Node profiles table: capabilities and benchmark results as JSON
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS node_profiles (
                node_id TEXT PRIMARY KEY,
                capabilities TEXT NOT NULL,
                cpu_profile TEXT,
                io_profile TEXT,
                memory_profile TEXT,
                gpu_profile TEXT,
                network_profile TEXT,
                FOREIGN KEY (node_id) REFERENCES nodes(node_id) ON DELETE CASCADE
            )
        """)

        # Jobs table: job submissions with lifecycle timestamps
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY,
                image TEXT NOT NULL,
                command TEXT,
                status TEXT DEFAULT 'queued',
                submitted_at TIMESTAMP NOT NULL,
                dispatched_at TIMESTAMP,
                dispatched_to_node TEXT,
                FOREIGN KEY (dispatched_to_node) REFERENCES nodes(node_id)
            )
        """)

        # Job results table: execution outcomes with completion timestamp
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS job_results (
                job_id TEXT PRIMARY KEY,
                node_id TEXT NOT NULL,
                success BOOLEAN NOT NULL,
                runtime_seconds REAL NOT NULL,
                exit_code INTEGER NOT NULL,
                completed_at TIMESTAMP NOT NULL,
                FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE CASCADE,
                FOREIGN KEY (node_id) REFERENCES nodes(node_id)
            )
        """)

        # Runs table: one row per experiment, so results from different
        # policies can be told apart instead of piling into one job history.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                label TEXT,
                policy TEXT NOT NULL,
                trace TEXT,
                started_at TIMESTAMP NOT NULL,
                finished_at TIMESTAMP,
                cluster_snapshot TEXT,
                notes TEXT
            )
        """)

        _migrate_schema(cursor)

        # Indexes for common queries
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_jobs_status
            ON jobs(status)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_jobs_run
            ON jobs(run_id)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_jobs_submitted
            ON jobs(submitted_at)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_job_results_completed
            ON job_results(completed_at)
        """)

        conn.commit()


# ============================================================================
# Node Operations
# ============================================================================

def register_node(node_id: str, hostname: str, agent_url: str) -> None:
    """Register a new node in the database."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO nodes
            (node_id, hostname, agent_url, registered_at)
            VALUES (?, ?, ?, ?)
        """, (node_id, hostname, agent_url, to_iso(utc_now())))


def save_node_profile(
    node_id: str,
    capabilities: Dict[str, Any],
    cpu_profile: Optional[Dict] = None,
    io_profile: Optional[Dict] = None,
    memory_profile: Optional[Dict] = None,
    gpu_profile: Optional[Dict] = None,
) -> None:
    """Save node profile with capabilities and benchmarks."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO node_profiles
            (node_id, capabilities, cpu_profile, io_profile, memory_profile, gpu_profile)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            node_id,
            json.dumps(capabilities),
            json.dumps(cpu_profile) if cpu_profile else None,
            json.dumps(io_profile) if io_profile else None,
            json.dumps(memory_profile) if memory_profile else None,
            json.dumps(gpu_profile) if gpu_profile else None,
        ))


def update_heartbeat(node_id: str, current_load: float) -> None:
    """Update node heartbeat and load."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE nodes
            SET last_heartbeat = ?, current_load = ?
            WHERE node_id = ?
        """, (to_iso(utc_now()), current_load, node_id))


def get_node(node_id: str) -> Optional[Dict]:
    """Retrieve node metadata."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM nodes WHERE node_id = ?", (node_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def get_all_nodes() -> List[Dict]:
    """Retrieve all registered nodes."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM nodes")
        return [dict(row) for row in cursor.fetchall()]


# ============================================================================
# Job Operations
# ============================================================================

def submit_job(
    job_id: str,
    image: str,
    command: Optional[str] = None,
    run_id: Optional[str] = None,
    submitted_at: Optional[datetime] = None,
    requirements: Optional[Any] = None,
) -> None:
    """
    Record a job submission.

    `submitted_at` should be the time the client submitted the job, not the
    time this row is written; queue wait is measured from it.
    """
    if submitted_at is None:
        submitted_at = utc_now()

    workload_type = cpu_request = memory_mb = requires_gpu = job_size = None

    if requirements is not None:
        workload_type = getattr(requirements.workload_type, "value",
                                requirements.workload_type)
        cpu_request = requirements.cpu_request
        memory_mb = requirements.memory_mb
        requires_gpu = int(bool(requirements.requires_gpu))
        job_size = requirements.size

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO jobs
            (job_id, image, command, status, submitted_at, run_id,
             workload_type, cpu_request, memory_mb, requires_gpu, job_size)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (job_id, image, command, "queued", to_iso(submitted_at), run_id,
              workload_type, cpu_request, memory_mb, requires_gpu, job_size))


def dispatch_job(job_id: str, node_id: str, dispatched_at: Optional[datetime] = None) -> None:
    """
    Record job dispatch to a node.

    A short job can finish and call back before the dispatcher gets here, so
    the status is only advanced when it is not already terminal. Writing
    'dispatched' unconditionally would resurrect a finished job, leaving it
    permanently in flight and stalling the drain check -- which is how a job
    that failed in ten milliseconds used to hang a whole run.

    The timestamp and node are still recorded either way: queue wait is
    measured from dispatched_at, so losing it would lose the measurement.
    """
    if dispatched_at is None:
        dispatched_at = utc_now()

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE jobs
            SET dispatched_at = ?,
                dispatched_to_node = ?,
                status = CASE
                    WHEN status IN ('completed', 'failed') THEN status
                    ELSE 'dispatched'
                END
            WHERE job_id = ?
        """, (to_iso(dispatched_at), node_id, job_id))


def record_job_result(
    job_id: str,
    node_id: str,
    success: bool,
    runtime_seconds: float,
    exit_code: int,
    completed_at: Optional[datetime] = None,
) -> None:
    """Record job execution result."""
    if completed_at is None:
        completed_at = utc_now()

    with get_db() as conn:
        cursor = conn.cursor()

        # Insert result
        cursor.execute("""
            INSERT OR REPLACE INTO job_results
            (job_id, node_id, success, runtime_seconds, exit_code, completed_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (job_id, node_id, success, runtime_seconds, exit_code, to_iso(completed_at)))

        # Update job status
        status = "completed" if success else "failed"
        cursor.execute("""
            UPDATE jobs
            SET status = ?
            WHERE job_id = ?
        """, (status, job_id))


def mark_job_failed(job_id: str) -> None:
    """
    Mark a job as failed without an execution result.

    Used when the dispatcher gives up before the job ever ran, so there is no
    runtime or exit code to record in job_results.
    """
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE jobs
            SET status = ?
            WHERE job_id = ?
        """, ("failed", job_id))


def get_job(job_id: str) -> Optional[Dict]:
    """Retrieve job metadata."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def get_job_result(job_id: str) -> Optional[Dict]:
    """Retrieve job execution result."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM job_results WHERE job_id = ?", (job_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def get_all_jobs() -> List[Dict]:
    """Retrieve all jobs."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM jobs ORDER BY submitted_at DESC")
        return [dict(row) for row in cursor.fetchall()]


def get_jobs_by_status(status: str) -> List[Dict]:
    """Retrieve jobs by status (queued, dispatched, completed, failed)."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM jobs WHERE status = ? ORDER BY submitted_at DESC",
            (status,)
        )
        return [dict(row) for row in cursor.fetchall()]


def get_jobs_for_node(node_id: str) -> List[Dict]:
    """Retrieve jobs dispatched to a specific node."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM jobs WHERE dispatched_to_node = ? ORDER BY dispatched_at DESC",
            (node_id,)
        )
        return [dict(row) for row in cursor.fetchall()]


# ============================================================================
# Experiment Runs
# ============================================================================

def start_run(
    run_id: str,
    policy: str,
    label: Optional[str] = None,
    trace: Optional[str] = None,
    cluster_snapshot: Optional[Any] = None,
    notes: Optional[str] = None,
) -> None:
    """
    Open an experiment run.

    `cluster_snapshot` records which nodes took part and what they were, so a
    result can be tied to the hardware that produced it after the fact.
    """
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO runs
            (run_id, label, policy, trace, started_at, cluster_snapshot, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            run_id,
            label,
            policy,
            trace,
            to_iso(utc_now()),
            json.dumps(cluster_snapshot) if cluster_snapshot is not None else None,
            notes,
        ))


def finish_run(run_id: str) -> None:
    """Close an experiment run."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE runs SET finished_at = ? WHERE run_id = ?
        """, (to_iso(utc_now()), run_id))


def get_run(run_id: str) -> Optional[Dict]:
    """Retrieve a run's metadata."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def get_all_runs() -> List[Dict]:
    """Retrieve all runs, newest first."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM runs ORDER BY started_at DESC")
        return [dict(row) for row in cursor.fetchall()]


def get_run_jobs(run_id: str) -> List[Dict]:
    """
    Every job in a run with its execution result attached.

    LEFT JOIN so jobs that never completed still appear -- an experiment that
    silently dropped jobs must be visible in the export, not absent from it.
    """
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                j.job_id, j.image, j.command, j.status, j.run_id,
                j.submitted_at, j.dispatched_at, j.dispatched_to_node,
                j.workload_type, j.cpu_request, j.memory_mb, j.requires_gpu,
                j.job_size,
                r.success, r.runtime_seconds, r.exit_code, r.completed_at
            FROM jobs j
            LEFT JOIN job_results r ON j.job_id = r.job_id
            WHERE j.run_id = ?
            ORDER BY j.submitted_at
        """, (run_id,))
        return [dict(row) for row in cursor.fetchall()]


def get_run_progress(run_id: str) -> Dict[str, Any]:
    """Status counts for a run, used to detect when a trace has drained."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status = 'queued' THEN 1 ELSE 0 END) as queued,
                SUM(CASE WHEN status = 'dispatched' THEN 1 ELSE 0 END) as dispatched,
                SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed
            FROM jobs
            WHERE run_id = ?
        """, (run_id,))
        row = cursor.fetchone()
        progress = {k: (v or 0) for k, v in dict(row).items()} if row else {}
        progress["terminal"] = progress.get("completed", 0) + progress.get("failed", 0)
        return progress


# ============================================================================
# Analytics / Metrics
# ============================================================================

def get_job_statistics() -> Dict[str, Any]:
    """Get overall job execution statistics."""
    with get_db() as conn:
        cursor = conn.cursor()

        # Total jobs and status breakdown
        cursor.execute("""
            SELECT
                COUNT(*) as total_jobs,
                SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                SUM(CASE WHEN status = 'dispatched' THEN 1 ELSE 0 END) as dispatched,
                SUM(CASE WHEN status = 'queued' THEN 1 ELSE 0 END) as queued
            FROM jobs
        """)
        row = cursor.fetchone()
        job_stats = dict(row) if row else {}

        # Execution time statistics for completed jobs
        cursor.execute("""
            SELECT
                COUNT(*) as successful_jobs,
                AVG(runtime_seconds) as avg_runtime_seconds,
                MIN(runtime_seconds) as min_runtime_seconds,
                MAX(runtime_seconds) as max_runtime_seconds
            FROM job_results
            WHERE success = 1
        """)
        row = cursor.fetchone()
        exec_stats = dict(row) if row else {}

        return {**job_stats, **exec_stats}


def get_node_job_summary(node_id: str) -> Dict[str, Any]:
    """Get job execution summary for a specific node."""
    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                COUNT(*) as total_jobs_on_node,
                SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successful,
                SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as failed,
                AVG(runtime_seconds) as avg_runtime_seconds
            FROM job_results
            WHERE node_id = ?
        """, (node_id,))
        row = cursor.fetchone()
        return dict(row) if row else {}
