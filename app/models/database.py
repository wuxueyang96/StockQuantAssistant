import os
from typing import Optional, Tuple
import duckdb
import pandas as pd
from app.config import Config


class DatabaseManager:
    def __init__(self):
        self._connections = {}

    def get_connection(self, market: str) -> duckdb.DuckDBPyConnection:
        if market not in self._connections:
            db_path = Config.DB_PATHS.get(market)
            if not db_path:
                raise ValueError(f"未知市场: {market}")
            os.makedirs(os.path.dirname(db_path), exist_ok=True)
            self._connections[market] = duckdb.connect(db_path)
        return self._connections[market]

    def _get_metadata_conn(self) -> duckdb.DuckDBPyConnection:
        if 'metadata' not in self._connections:
            os.makedirs(Config.DATA_DIR, exist_ok=True)
            self._connections['metadata'] = duckdb.connect(Config.METADATA_DB_PATH)
            self._init_metadata()
        return self._connections['metadata']

    def _init_metadata(self):
        conn = self._get_metadata_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS stock_codes (
                name TEXT PRIMARY KEY,
                a_code TEXT,
                hk_code TEXT,
                us_code TEXT
            )
        """)
        cols = conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'workflows'"
        ).fetchall()
        col_names = [c[0] for c in cols]
        if col_names and 'market' not in col_names:
            conn.execute("DROP TABLE workflows")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS workflows (
                id TEXT PRIMARY KEY,
                market TEXT,
                stock_code TEXT,
                interval TEXT,
                "table" TEXT,
                db_path TEXT,
                created_at TEXT,
                active INTEGER
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS workflows (
                id TEXT PRIMARY KEY,
                market TEXT,
                stock_code TEXT,
                interval TEXT,
                "table" TEXT,
                db_path TEXT,
                created_at TEXT,
                active INTEGER
            )
        """)
        try:
            conn.execute("ALTER TABLE workflows DROP COLUMN data")
        except Exception:
            pass

    def quote(self, name: str) -> str:
        return f'"{name}"'

    def table_exists(self, market: str, table_name: str) -> bool:
        conn = self.get_connection(market)
        result = conn.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_name = ?",
            [table_name]
        ).fetchone()
        return result[0] > 0

    def create_stock_table(self, market: str, table_name: str):
        conn = self.get_connection(market)
        tbl = self.quote(table_name)
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {tbl} (
                timestamp TIMESTAMP PRIMARY KEY,
                open DOUBLE,
                high DOUBLE,
                low DOUBLE,
                close DOUBLE,
                volume BIGINT,
                dividends DOUBLE,
                stock_splits DOUBLE
            )
        """)

    def get_latest_timestamp(self, market: str, table_name: str):
        if not self.table_exists(market, table_name):
            return None
        conn = self.get_connection(market)
        tbl = self.quote(table_name)
        result = conn.execute(
            f"SELECT MAX(timestamp) FROM {tbl}"
        ).fetchone()
        return result[0] if result and result[0] else None

    def insert_data(self, market: str, table_name: str, df: pd.DataFrame) -> int:
        if df.empty:
            return 0

        conn = self.get_connection(market)
        df = df.copy()
        df.index.name = 'timestamp'
        df = df.reset_index()

        latest_ts = self.get_latest_timestamp(market, table_name)
        if latest_ts:
            df = df[df['timestamp'] > pd.Timestamp(latest_ts)]

        if df.empty:
            return 0

        tbl = self.quote(table_name)
        conn.execute(f"INSERT INTO {tbl} SELECT * FROM df")
        return len(df)

    def get_data(self, market: str, table_name: str, limit: int = 200) -> pd.DataFrame:
        if not self.table_exists(market, table_name):
            return pd.DataFrame()
        conn = self.get_connection(market)
        tbl = self.quote(table_name)
        return conn.execute(
            f"SELECT * FROM {tbl} ORDER BY timestamp DESC LIMIT {limit}"
        ).fetchdf()

    def close_all(self):
        for conn in self._connections.values():
            conn.close()
        self._connections.clear()

    def drop_table(self, market: str, table_name: str):
        conn = self.get_connection(market)
        tbl = self.quote(table_name)
        conn.execute(f"DROP TABLE IF EXISTS {tbl}")

    def upsert_stock_code(self, name: str, a_code: str = None, hk_code: str = None, us_code: str = None):
        conn = self._get_metadata_conn()
        existing = conn.execute(
            "SELECT a_code, hk_code, us_code FROM stock_codes WHERE name = ?",
            [name]
        ).fetchone()

        if existing:
            new_a = a_code if a_code is not None else existing[0]
            new_hk = hk_code if hk_code is not None else existing[1]
            new_us = us_code if us_code is not None else existing[2]
            conn.execute(
                "UPDATE stock_codes SET a_code = ?, hk_code = ?, us_code = ? WHERE name = ?",
                [new_a, new_hk, new_us, name]
            )
        else:
            conn.execute(
                "INSERT INTO stock_codes (name, a_code, hk_code, us_code) VALUES (?, ?, ?, ?)",
                [name, a_code, hk_code, us_code]
            )

    def get_stock_codes(self, name: str) -> Optional[Tuple[str, str, str]]:
        conn = self._get_metadata_conn()
        row = conn.execute(
            "SELECT a_code, hk_code, us_code FROM stock_codes WHERE name = ?",
            [name]
        ).fetchone()
        if row:
            return row[0], row[1], row[2]
        return None

    def get_all_stock_codes(self) -> pd.DataFrame:
        conn = self._get_metadata_conn()
        return conn.execute("SELECT * FROM stock_codes ORDER BY name").fetchdf()

    def delete_stock_code(self, name: str) -> bool:
        conn = self._get_metadata_conn()
        result = conn.execute("DELETE FROM stock_codes WHERE name = ?", [name])
        return result.fetchall() or False

    def save_workflow(self, wf_id: str, wf_data: dict):
        conn = self._get_metadata_conn()
        conn.execute(
            "INSERT OR REPLACE INTO workflows (id, market, stock_code, interval, \"table\", db_path, created_at, active)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                wf_id,
                wf_data.get('market'),
                wf_data.get('stock_code'),
                wf_data.get('interval'),
                wf_data.get('table'),
                wf_data.get('db_path'),
                wf_data.get('created_at'),
                1 if wf_data.get('active', True) else 0,
            ]
        )

    def load_workflows(self) -> dict:
        conn = self._get_metadata_conn()
        rows = conn.execute(
            "SELECT id, market, stock_code, interval, \"table\", db_path, created_at, active FROM workflows"
        ).fetchall()
        workflows = {}
        for row in rows:
            wf_id, market, stock_code, interval, tbl, db_path, created_at, active = row
            workflows[wf_id] = {
                'market': market,
                'stock_code': stock_code,
                'interval': interval,
                'table': tbl,
                'db_path': db_path,
                'created_at': created_at,
                'active': bool(active),
            }
        return workflows

    def delete_workflow_by_id(self, wf_id: str) -> bool:
        conn = self._get_metadata_conn()
        conn.execute("DELETE FROM workflows WHERE id = ?", [wf_id])
        return True


db_manager = DatabaseManager()
