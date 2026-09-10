"""Lightweight SQLite cache for AkShare responses.

The cache keeps AkShare column names intact by storing each dataset as a
dedicated table. Tables are created lazily with the column names detected
from the first inserted record, and new columns are appended automatically
if AkShare adds more fields in the future.
"""

from __future__ import annotations

import atexit
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
import threading
import time
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, TypeVar

import numpy as np
import pandas as pd


ISO_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"
_T = TypeVar("_T")
_PATH_LOCKS: dict[Path, threading.RLock] = {}
_PATH_LOCKS_GUARD = threading.Lock()


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime(ISO_FORMAT)


def _infer_sql_type(value: Any) -> str:
    if isinstance(value, (int, np.integer)):
        return "INTEGER"
    if isinstance(value, (float, np.floating)):
        return "REAL"
    return "TEXT"


def _normalize(value: Any) -> Any:
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, (np.generic,)):
        return value.item()
    if pd.isna(value):  # type: ignore[arg-type]
        return None
    return value


def _quote_identifier(name: str) -> str:
    return f'"{name.replace(chr(34), chr(34) * 2)}"'


def _path_lock(database_path: Path) -> threading.RLock:
    with _PATH_LOCKS_GUARD:
        return _PATH_LOCKS.setdefault(database_path, threading.RLock())


class AkshareSQLiteCache:
    """Simple SQLite-backed cache with insert-or-update semantics."""

    def __init__(
        self,
        database_path: Path,
        *,
        busy_timeout_seconds: float | None = None,
        max_retries: int = 5,
    ) -> None:
        database_path = database_path.expanduser().resolve()
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self._database_path = database_path
        configured_timeout = os.getenv("MARKET_CACHE_SQLITE_TIMEOUT", "30")
        self._busy_timeout_seconds = max(
            0.1,
            float(configured_timeout if busy_timeout_seconds is None else busy_timeout_seconds),
        )
        self._max_retries = max(1, max_retries)
        self._write_lock = _path_lock(database_path)
        self._connections: list[sqlite3.Connection] = []
        self._connections_lock = threading.Lock()
        self._local = threading.local()
        self._closed = False
        self._atexit_registered = False
        self._register_atexit()

    def _register_atexit(self) -> None:
        if not self._atexit_registered:
            atexit.register(self.close)
            self._atexit_registered = True

    def _get_conn(self) -> sqlite3.Connection:
        if self._closed:
            raise RuntimeError("SQLite cache is closed")
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(
                self._database_path,
                timeout=self._busy_timeout_seconds,
                check_same_thread=False,
            )
            conn.row_factory = sqlite3.Row
            conn.execute(f"PRAGMA busy_timeout={int(self._busy_timeout_seconds * 1000)};")
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            self._local.conn = conn
            with self._connections_lock:
                self._connections.append(conn)
        return conn

    @staticmethod
    def _is_locked_error(exc: sqlite3.OperationalError) -> bool:
        message = str(exc).lower()
        return "locked" in message or "busy" in message

    def _retry_delay(self, attempt: int) -> float:
        return min(0.05 * (2**attempt), 1.0)

    def _run_read(self, operation: Callable[[sqlite3.Connection], _T]) -> _T:
        for attempt in range(self._max_retries):
            try:
                return operation(self._get_conn())
            except sqlite3.OperationalError as exc:
                if not self._is_locked_error(exc) or attempt + 1 >= self._max_retries:
                    raise
                time.sleep(self._retry_delay(attempt))
        raise AssertionError("unreachable")

    def _run_write(self, operation: Callable[[sqlite3.Connection], _T]) -> _T:
        for attempt in range(self._max_retries):
            with self._write_lock:
                conn = self._get_conn()
                try:
                    conn.execute("BEGIN IMMEDIATE;")
                    result = operation(conn)
                    conn.commit()
                    return result
                except sqlite3.OperationalError as exc:
                    conn.rollback()
                    if not self._is_locked_error(exc) or attempt + 1 >= self._max_retries:
                        raise
                except Exception:
                    conn.rollback()
                    raise
            time.sleep(self._retry_delay(attempt))
        raise AssertionError("unreachable")

    # ------------------------------------------------------------------
    # Schema helpers
    # ------------------------------------------------------------------
    def _table_columns(
        self,
        table: str,
        conn: sqlite3.Connection | None = None,
    ) -> Dict[str, str]:
        conn = conn or self._get_conn()
        cursor = conn.execute(f'PRAGMA table_info("{table}");')
        return {row[1]: row[2] for row in cursor.fetchall()}

    def _ensure_table(
        self,
        conn: sqlite3.Connection,
        table: str,
        sample_record: Dict[str, Any],
        key_columns: Sequence[str],
    ) -> None:
        columns = self._table_columns(table, conn)
        if not columns:
            col_defs: List[str] = []
            for column, value in sample_record.items():
                sql_type = _infer_sql_type(value)
                col_defs.append(f'"{column}" {sql_type}')
            pk_clause = f" ,PRIMARY KEY ({', '.join(_quote_identifier(col) for col in key_columns)})" if key_columns else ""
            create_sql = f'CREATE TABLE IF NOT EXISTS "{table}" (' + ", ".join(col_defs) + pk_clause + ");"
            conn.execute(create_sql)
            return

        # Add missing columns on-the-fly.
        for column, value in sample_record.items():
            if column not in columns:
                sql_type = _infer_sql_type(value)
                conn.execute(f'ALTER TABLE "{table}" ADD COLUMN "{column}" {sql_type};')

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def upsert_records(
        self,
        table: str,
        records: Iterable[Dict[str, Any]],
        key_columns: Sequence[str],
    ) -> None:
        payload: List[Dict[str, Any]] = []
        for record in records:
            normalized = {column: _normalize(value) for column, value in record.items()}
            if "缓存时间" not in normalized:
                normalized["缓存时间"] = _utcnow()
            payload.append(normalized)

        if not payload:
            return

        columns = list(dict.fromkeys(column for record in payload for column in record))
        sample = {
            column: next(
                (record.get(column) for record in payload if record.get(column) is not None),
                None,
            )
            for column in columns
        }

        def write(conn: sqlite3.Connection) -> None:
            self._ensure_table(conn, table, sample, key_columns)
            quoted_columns = ", ".join(_quote_identifier(col) for col in columns)
            placeholders = ", ".join(["?"] * len(columns))
            conflict_clause = ", ".join(_quote_identifier(col) for col in key_columns)
            update_clause = ", ".join(f"{_quote_identifier(col)}=excluded.{_quote_identifier(col)}" for col in columns if col not in key_columns)
            sql = f"INSERT INTO {_quote_identifier(table)} ({quoted_columns}) VALUES ({placeholders})"
            if key_columns:
                sql += f" ON CONFLICT ({conflict_clause})"
                sql += f" DO UPDATE SET {update_clause}" if update_clause else " DO NOTHING"
            rows = [[record.get(column) for column in columns] for record in payload]
            conn.executemany(sql, rows)

        self._run_write(write)

    def fetch_records(
        self,
        table: str,
        filters: Optional[Dict[str, Any]] = None,
        ttl_seconds: Optional[int] = None,
        order_by: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        if not self._run_read(lambda conn: self._table_columns(table, conn)):
            return []

        clauses: List[str] = []
        params: List[Any] = []
        if filters:
            for column, value in filters.items():
                clauses.append(f'"{column}" = ?')
                params.append(value)
        if ttl_seconds is not None:
            threshold = (datetime.now(timezone.utc) - timedelta(seconds=ttl_seconds)).strftime(ISO_FORMAT)
            clauses.append('"缓存时间" >= ?')
            params.append(threshold)

        sql = f'SELECT * FROM "{table}"'
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        if order_by:
            sql += f" ORDER BY {order_by}"
        if limit is not None:
            sql += f" LIMIT {limit}"

        def read(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
            cursor = conn.execute(sql, params)
            return [dict(row) for row in cursor.fetchall()]

        return self._run_read(read)

    def delete_records(
        self,
        table: str,
        filters: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not self._run_read(lambda conn: self._table_columns(table, conn)):
            return
        clauses: List[str] = []
        params: List[Any] = []
        if filters:
            for column, value in filters.items():
                clauses.append(f'"{column}" = ?')
                params.append(value)
        sql = f"DELETE FROM {_quote_identifier(table)}"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        self._run_write(lambda conn: conn.execute(sql, params))

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        with self._connections_lock:
            connections, self._connections = self._connections, []
        for conn in connections:
            try:
                conn.close()
            except sqlite3.Error:
                pass
        self._local.conn = None

    def __del__(self) -> None:
        if not self._closed:
            self.close()
