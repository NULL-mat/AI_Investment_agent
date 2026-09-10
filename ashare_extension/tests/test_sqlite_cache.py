from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import sqlite3
import time

from ashare_extension.data.sqlite_cache import AkshareSQLiteCache


def test_upsert_handles_heterogeneous_rows_and_adds_columns(tmp_path):
    cache = AkshareSQLiteCache(tmp_path / "cache.db")

    cache.upsert_records(
        "quotes",
        [
            {"symbol": "600519", "date": "2026-09-08", "close": 100.0},
            {
                "symbol": "600519",
                "date": "2026-09-09",
                "close": 101.0,
                "volume": 10,
            },
        ],
        key_columns=["symbol", "date"],
    )
    cache.upsert_records(
        "quotes",
        [
            {
                "symbol": "600519",
                "date": "2026-09-09",
                "close": 102.0,
                "amount": 1_000.0,
            }
        ],
        key_columns=["symbol", "date"],
    )

    rows = cache.fetch_records("quotes", order_by='"date" ASC')
    cache.close()

    assert len(rows) == 2
    assert rows[1]["close"] == 102.0
    assert "volume" in rows[0]
    assert "amount" in rows[0]


def test_multiple_instances_can_write_same_database_concurrently(tmp_path):
    database_path = tmp_path / "concurrent.db"

    def write(index: int) -> None:
        cache = AkshareSQLiteCache(
            database_path,
            busy_timeout_seconds=2,
            max_retries=8,
        )
        try:
            cache.upsert_records(
                "history",
                [
                    {
                        "symbol": "600519",
                        "date": f"2026-08-{index + 1:02d}",
                        "close": float(index),
                    }
                ],
                key_columns=["symbol", "date"],
            )
        finally:
            cache.close()

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(write, range(24)))

    cache = AkshareSQLiteCache(database_path)
    rows = cache.fetch_records("history")
    cache.close()

    assert len(rows) == 24


def test_write_waits_for_external_database_lock(tmp_path):
    database_path = tmp_path / "externally-locked.db"
    seed = AkshareSQLiteCache(database_path)
    seed.upsert_records(
        "quotes",
        [{"symbol": "600519", "close": 100.0}],
        key_columns=["symbol"],
    )
    seed.close()

    blocker = sqlite3.connect(database_path)
    blocker.execute("BEGIN IMMEDIATE;")
    blocker.execute('UPDATE "quotes" SET "close" = 101.0')

    def write_after_wait() -> None:
        cache = AkshareSQLiteCache(
            database_path,
            busy_timeout_seconds=0.1,
            max_retries=8,
        )
        try:
            cache.upsert_records(
                "quotes",
                [{"symbol": "000001", "close": 10.0}],
                key_columns=["symbol"],
            )
        finally:
            cache.close()

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(write_after_wait)
        time.sleep(0.25)
        blocker.commit()
        future.result(timeout=3)
    blocker.close()

    cache = AkshareSQLiteCache(database_path)
    rows = cache.fetch_records("quotes")
    cache.close()

    assert {row["symbol"] for row in rows} == {"600519", "000001"}
