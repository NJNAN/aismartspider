"""Tests for result writer normalization."""

from __future__ import annotations

import json
import sqlite3

from aismartspider.output import SQLiteWriter


def test_sqlite_writer_serializes_lists(tmp_path):
    db_path = tmp_path / "records.db"
    writer = SQLiteWriter(db_path=str(db_path), table="records")
    records = [
        {"title": "Example", "links": ["http://a", "http://b"], "meta": {"author": "tester"}},
    ]

    writer.write(records)

    conn = sqlite3.connect(db_path)
    cursor = conn.execute('SELECT title, links, meta FROM "records"')
    row = cursor.fetchone()
    conn.close()

    assert row[0] == "Example"
    assert json.loads(row[1]) == ["http://a", "http://b"]
    assert json.loads(row[2]) == {"author": "tester"}
