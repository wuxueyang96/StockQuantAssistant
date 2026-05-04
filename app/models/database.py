import logging
import os
from typing import Optional, Tuple

import duckdb
import pandas as pd
from app.config import Config

logger = logging.getLogger(__name__)


class DatabaseManager:
    def __init__(self):
        self._conn = None
        self._metadata_loaded = False

    def _get_conn(self) -> duckdb.DuckDBPyConnection:
        if self._conn is None:
            self._conn = duckdb.connect(':memory:')
            self._setup_httpfs()
        return self._conn

    def _setup_httpfs(self):
        try:
            self._conn.execute("LOAD httpfs")
        except Exception:
            pass
        if not Config.OSS_BUCKET:
            return
        parts = [
            f"TYPE S3",
            f"KEY_ID '{Config.OSS_ACCESS_KEY_ID or ''}'",
            f"SECRET '{Config.OSS_ACCESS_KEY_SECRET or ''}'",
            f"REGION '{Config.OSS_REGION}'",
        ]
        if Config.OSS_ENDPOINT:
            parts.append(f"ENDPOINT '{Config.OSS_ENDPOINT}'")
        self._conn.execute(
            "CREATE SECRET IF NOT EXISTS oss (" + ", ".join(parts) + ")"
        )

    def _data_url(self, market: str, table_name: str) -> str:
        if Config.OSS_BUCKET:
            return f"s3://{Config.OSS_BUCKET}/{market}/{table_name}.parquet"
        os.makedirs(os.path.join(Config.DATA_DIR, market), exist_ok=True)
        return os.path.join(Config.DATA_DIR, market, f"{table_name}.parquet")

    def _meta_url(self, table_name: str) -> str:
        if Config.OSS_BUCKET:
            return f"s3://{Config.OSS_BUCKET}/metadata/{table_name}.parquet"
        os.makedirs(os.path.join(Config.DATA_DIR, 'metadata'), exist_ok=True)
        return os.path.join(Config.DATA_DIR, 'metadata', f"{table_name}.parquet")

    def _try_read_parquet(self, url: str) -> pd.DataFrame:
        try:
            return self._get_conn().execute(
                f"SELECT * FROM read_parquet('{url}')"
            ).fetchdf()
        except Exception:
            return pd.DataFrame()

    def _write_parquet(self, df: pd.DataFrame, url: str):
        conn = self._get_conn()
        conn.register('__df', df)
        conn.execute(
            f"COPY __df TO '{url}' (FORMAT PARQUET, OVERWRITE_OR_IGNORE true)"
        )
        conn.unregister('__df')

    def quote(self, name: str) -> str:
        return f'"{name}"'

    # ── connection helpers (for test backward compat) ──

    def get_connection(self, market: str) -> duckdb.DuckDBPyConnection:
        if market not in ('a', 'hk', 'us'):
            raise ValueError(f"未知市场: {market}")
        return self._get_conn()

    def _get_metadata_conn(self) -> duckdb.DuckDBPyConnection:
        conn = self._get_conn()
        self._init_metadata()
        return conn

    def close_all(self):
        if self._conn is not None:
            self._flush_metadata()
            self._conn.close()
            self._conn = None
            self._metadata_loaded = False

    # ── metadata tables ──

    def _init_metadata(self):
        if self._metadata_loaded:
            return
        self._metadata_loaded = True
        conn = self._get_conn()
        try:
            conn.execute("SELECT COUNT(*) FROM stock_codes").fetchone()
            return
        except Exception:
            pass

        for table_name in ('stock_codes', 'workflows'):
            url = self._meta_url(table_name)
            df = self._try_read_parquet(url)
            if df.empty:
                if table_name == 'stock_codes':
                    conn.execute("""
                        CREATE TABLE stock_codes (
                            name TEXT PRIMARY KEY,
                            a_code TEXT,
                            hk_code TEXT,
                            us_code TEXT
                        )
                    """)
                else:
                    conn.execute("""
                        CREATE TABLE workflows (
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
            else:
                conn.execute(f"CREATE TABLE {table_name} AS SELECT * FROM df")

    def _flush_metadata(self):
        if not self._metadata_loaded or self._conn is None:
            return
        for table_name in ('stock_codes', 'workflows'):
            url = self._meta_url(table_name)
            self._conn.execute(
                f"COPY {table_name} TO '{url}' (FORMAT PARQUET, OVERWRITE_OR_IGNORE true)"
            )

    # ── OHLCV data ──

    def table_exists(self, market: str, table_name: str) -> bool:
        url = self._data_url(market, table_name)
        try:
            result = self._get_conn().execute(
                f"SELECT COUNT(*) FROM read_parquet('{url}')"
            ).fetchone()
            return result is not None and result[0] > 0
        except Exception:
            return False

    def create_stock_table(self, market: str, table_name: str):
        pass

    def get_latest_timestamp(self, market: str, table_name: str):
        url = self._data_url(market, table_name)
        try:
            result = self._get_conn().execute(
                f"SELECT MAX(timestamp) FROM read_parquet('{url}')"
            ).fetchone()
            return result[0] if result and result[0] else None
        except Exception:
            return None

    def insert_data(self, market: str, table_name: str, df: pd.DataFrame) -> int:
        if df.empty:
            return 0

        df = df.copy()
        df.columns = [c.lower() for c in df.columns]

        if 'timestamp' not in df.columns:
            df.index.name = 'timestamp'
            df = df.reset_index()

        cols = ['timestamp', 'open', 'high', 'low', 'close', 'volume',
                'dividends', 'stock_splits']
        existing = [c for c in cols if c in df.columns]
        df = df[existing]

        url = self._data_url(market, table_name)
        prev = self._try_read_parquet(url)

        if not prev.empty and 'timestamp' in prev.columns:
            prev['timestamp'] = pd.to_datetime(prev['timestamp'])
            latest = prev['timestamp'].max()
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df = df[df['timestamp'] > latest]

        if df.empty:
            return 0

        merged = pd.concat([prev, df], ignore_index=True)
        merged = merged.drop_duplicates(subset=['timestamp'])
        merged = merged.sort_values('timestamp')
        self._write_parquet(merged, url)
        return len(df)

    def get_data(self, market: str, table_name: str, limit: int = 200) -> pd.DataFrame:
        url = self._data_url(market, table_name)
        try:
            return self._get_conn().execute(
                f"SELECT * FROM read_parquet('{url}') "
                f"ORDER BY timestamp DESC LIMIT {limit}"
            ).fetchdf()
        except Exception:
            return pd.DataFrame()

    def drop_table(self, market: str, table_name: str):
        url = self._data_url(market, table_name)
        if url.startswith('s3://'):
            self._get_conn().execute(
                f"COPY (SELECT 1 AS timestamp WHERE false) TO '{url}' "
                f"(FORMAT PARQUET, OVERWRITE_OR_IGNORE true)"
            )
        else:
            try:
                os.remove(url)
            except FileNotFoundError:
                pass

    # ── stock_codes ──

    def upsert_stock_code(self, name: str, a_code: str = None,
                          hk_code: str = None, us_code: str = None):
        conn = self._get_metadata_conn()
        existing = conn.execute(
            "SELECT a_code, hk_code, us_code FROM stock_codes WHERE name = ?",
            [name]
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE stock_codes SET a_code = ?, hk_code = ?, us_code = ? WHERE name = ?",
                [
                    a_code if a_code is not None else existing[0],
                    hk_code if hk_code is not None else existing[1],
                    us_code if us_code is not None else existing[2],
                    name,
                ]
            )
        else:
            conn.execute(
                "INSERT INTO stock_codes (name, a_code, hk_code, us_code) VALUES (?, ?, ?, ?)",
                [name, a_code, hk_code, us_code]
            )
        self._flush_metadata()

    def get_stock_codes(self, name: str) -> Optional[Tuple[str, str, str]]:
        conn = self._get_metadata_conn()
        row = conn.execute(
            "SELECT a_code, hk_code, us_code FROM stock_codes WHERE name = ?", [name]
        ).fetchone()
        if row:
            return row[0], row[1], row[2]
        return None

    def get_all_stock_codes(self) -> pd.DataFrame:
        conn = self._get_metadata_conn()
        return conn.execute("SELECT * FROM stock_codes ORDER BY name").fetchdf()

    def delete_stock_code(self, name: str) -> bool:
        conn = self._get_metadata_conn()
        conn.execute("DELETE FROM stock_codes WHERE name = ?", [name])
        self._flush_metadata()
        return True

    # ── workflows ──

    def save_workflow(self, wf_id: str, wf_data: dict):
        conn = self._get_metadata_conn()
        conn.execute(
            "INSERT OR REPLACE INTO workflows "
            "(id, market, stock_code, interval, \"table\", db_path, created_at, active) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
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
        self._flush_metadata()

    def load_workflows(self) -> dict:
        conn = self._get_metadata_conn()
        rows = conn.execute(
            "SELECT id, market, stock_code, interval, \"table\", db_path, "
            "created_at, active FROM workflows"
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
        self._flush_metadata()
        return True


db_manager = DatabaseManager()
