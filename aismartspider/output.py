"""Result writer interfaces and implementations."""

from __future__ import annotations

import csv
import json
import sqlite3
from abc import ABC, abstractmethod
from typing import List, Dict


class ResultWriter(ABC):
    """Base interface for output adapters."""

    @abstractmethod
    def write(self, records: List[Dict[str, str]]) -> None:
        """Persist records to desired sink."""


class PrintWriter(ResultWriter):
    def write(self, records: List[Dict[str, str]]) -> None:
        from pprint import pprint

        pprint(records)


class TxtWriter(ResultWriter):
    def __init__(self, path: str = "output.txt") -> None:
        self.path = path

    def write(self, records: List[Dict[str, str]]) -> None:
        with open(self.path, "w", encoding="utf-8") as handle:
            for record in records:
                handle.write(str(record) + "\n")


class JsonWriter(ResultWriter):
    def __init__(self, path: str = "output.json") -> None:
        self.path = path

    def write(self, records: List[Dict[str, str]]) -> None:
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(records, handle, ensure_ascii=False, indent=2)


class CsvWriter(ResultWriter):
    def __init__(self, path: str = "output.csv") -> None:
        self.path = path

    def write(self, records: List[Dict[str, str]]) -> None:
        if not records:
            return
        with open(self.path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(records[0].keys()))
            writer.writeheader()
            writer.writerows(records)


class SQLiteWriter(ResultWriter):
    def __init__(self, db_path: str = "data.db", table: str = "records") -> None:
        self.db_path = db_path
        self.table = table

    def write(self, records: List[Dict[str, str]]) -> None:
        if not records:
            return
        columns = list(records[0].keys())
        placeholders = ",".join("?" for _ in columns)
        col_definitions = ",".join(f"{self._quote_identifier(col)} TEXT" for col in columns)
        column_list = ",".join(self._quote_identifier(col) for col in columns)
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            f"CREATE TABLE IF NOT EXISTS {self._quote_identifier(self.table)} ({col_definitions})"
        )
        conn.executemany(
            f"INSERT INTO {self._quote_identifier(self.table)} ({column_list}) VALUES ({placeholders})",
            [[record[col] for col in columns] for record in records],
        )
        conn.commit()
        conn.close()

    @staticmethod
    def _quote_identifier(identifier: str) -> str:
        safe = identifier.replace('"', '""')
        return f'"{safe}"'
