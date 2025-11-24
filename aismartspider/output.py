"""Result writer interfaces and implementations."""

from __future__ import annotations

import csv
import json
import sqlite3
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence


class ResultWriter(ABC):
    """Base interface for output adapters."""

    @abstractmethod
    def write(self, records: List[Dict[str, Any]]) -> None:
        """Persist records to desired sink."""


# --------------------------------------------------------------------------- #
# File-based writers
# --------------------------------------------------------------------------- #
class PrintWriter(ResultWriter):
    def write(self, records: List[Dict[str, Any]]) -> None:
        from pprint import pprint

        pprint(records)


class TxtWriter(ResultWriter):
    def __init__(self, path: str = "output.txt") -> None:
        self.path = Path(path)

    def write(self, records: List[Dict[str, Any]]) -> None:
        with self.path.open("w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False))
                handle.write("\n")


class JsonWriter(ResultWriter):
    def __init__(self, path: str = "output.json") -> None:
        self.path = Path(path)

    def write(self, records: List[Dict[str, Any]]) -> None:
        with self.path.open("w", encoding="utf-8") as handle:
            json.dump(records, handle, ensure_ascii=False, indent=2)


class CsvWriter(ResultWriter):
    def __init__(self, path: str = "output.csv") -> None:
        self.path = Path(path)

    def write(self, records: List[Dict[str, Any]]) -> None:
        if not records:
            return
        columns = _collect_columns(records)
        with self.path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            for record in records:
                normalized = _normalize_record(record, columns)
                writer.writerow(normalized)


# --------------------------------------------------------------------------- #
# Relational database writers (pluggable)
# --------------------------------------------------------------------------- #
class SQLWriter(ResultWriter, ABC):
    """Base helper for SQL-compatible storage backends."""

    placeholder = "?"
    column_type = "TEXT"

    def __init__(self, table: str = "records") -> None:
        self.table = table

    def write(self, records: List[Dict[str, Any]]) -> None:
        if not records:
            return

        columns = _collect_columns(records)
        normalized_rows = [_normalize_row_for_db(record, columns) for record in records]
        column_definitions = ", ".join(f"{self._quote_identifier(col)} {self.column_type}" for col in columns)
        column_list = ", ".join(self._quote_identifier(col) for col in columns)
        placeholders = ", ".join(self.placeholder for _ in columns)

        connection = self._connect()
        try:
            cursor = connection.cursor()
            cursor.execute(
                f"CREATE TABLE IF NOT EXISTS {self._quote_identifier(self.table)} ({column_definitions})"
            )
            cursor.executemany(
                f"INSERT INTO {self._quote_identifier(self.table)} ({column_list}) VALUES ({placeholders})",
                normalized_rows,
            )
            connection.commit()
        finally:
            try:
                cursor.close()  # type: ignore[has-type]
            except Exception:
                pass
            connection.close()

    @abstractmethod
    def _connect(self):
        raise NotImplementedError

    @abstractmethod
    def _quote_identifier(self, identifier: str) -> str:
        raise NotImplementedError


class SQLiteWriter(SQLWriter):
    def __init__(self, db_path: str = "data.db", table: str = "records") -> None:
        super().__init__(table=table)
        self.db_path = db_path

    def _connect(self):
        return sqlite3.connect(self.db_path)

    def _quote_identifier(self, identifier: str) -> str:
        safe = identifier.replace('"', '""')
        return f'"{safe}"'


class MySQLWriter(SQLWriter):
    placeholder = "%s"
    column_type = "LONGTEXT"

    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        database: str,
        table: str = "records",
    ) -> None:
        super().__init__(table=table)
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.database = database

    def _connect(self):
        try:
            import pymysql
        except ImportError as exc:
            raise ImportError("MySQL writer requires the 'mysql' extra: pip install aismartspider[mysql]") from exc

        return pymysql.connect(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            database=self.database,
            charset="utf8mb4",
            autocommit=False,
        )

    def _quote_identifier(self, identifier: str) -> str:
        safe = identifier.replace("`", "``")
        return f"`{safe}`"


class PostgresWriter(SQLWriter):
    placeholder = "%s"
    column_type = "TEXT"

    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        database: str,
        table: str = "records",
    ) -> None:
        super().__init__(table=table)
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.database = database

    def _connect(self):
        try:
            import psycopg2
        except ImportError as exc:
            raise ImportError("PostgreSQL writer requires the 'postgres' extra: pip install aismartspider[postgres]") from exc

        return psycopg2.connect(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            dbname=self.database,
        )

    def _quote_identifier(self, identifier: str) -> str:
        safe = identifier.replace('"', '""')
        return f'"{safe}"'


# --------------------------------------------------------------------------- #
# Helper utilities
# --------------------------------------------------------------------------- #
def _collect_columns(records: List[Dict[str, Any]]) -> List[str]:
    columns: List[str] = []
    seen: set[str] = set()
    for record in records:
        for key in record.keys():
            if key not in seen:
                columns.append(key)
                seen.add(key)
    return columns


def _normalize_record(record: Dict[str, Any], columns: Sequence[str]) -> Dict[str, str]:
    normalized: Dict[str, str] = {}
    for column in columns:
        normalized[column] = _normalize_cell(record.get(column))
    return normalized


def _normalize_row_for_db(record: Dict[str, Any], columns: Sequence[str]) -> List[str]:
    normalized = _normalize_record(record, columns)
    return [normalized[col] for col in columns]


def _normalize_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (str, int, float)):
        return str(value)
    return json.dumps(value, ensure_ascii=False)
