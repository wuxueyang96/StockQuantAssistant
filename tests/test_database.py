import os
import pandas as pd
import pytest
from app.models.database import DatabaseManager


class TestDatabaseManager:
    @pytest.fixture
    def db(self, temp_db_dir):
        from app.config import Config
        Config.DATA_DIR = temp_db_dir
        Config.DB_PATHS = {
            'a': os.path.join(temp_db_dir, 'a_stock.db'),
            'hk': os.path.join(temp_db_dir, 'hk_stock.db'),
            'us': os.path.join(temp_db_dir, 'us_stock.db'),
        }
        mgr = DatabaseManager()
        yield mgr
        mgr.close_all()

    def test_different_market_different_files(self, db, temp_db_dir):
        conn_a = db.get_connection('a')
        conn_hk = db.get_connection('hk')
        assert conn_a is not conn_hk

    def test_create_table_with_dots_in_name(self, db):
        db.create_stock_table('a', 'A_000001.SZ_daily')
        assert db.table_exists('a', 'A_000001.SZ_daily')

    def test_table_not_exists(self, db):
        assert not db.table_exists('a', 'nonexistent_table')

    def test_insert_and_get_data(self, db):
        db.create_stock_table('a', 'A_000001.SZ_daily')
        dates = pd.date_range('2024-01-01', periods=10, freq='B')
        df = pd.DataFrame({
            'Open': [10.0 + i for i in range(10)],
            'High': [11.0 + i for i in range(10)],
            'Low': [9.0 + i for i in range(10)],
            'Close': [10.5 + i for i in range(10)],
            'Volume': [1000000] * 10,
            'Dividends': [0.0] * 10,
            'Stock Splits': [0.0] * 10,
        }, index=dates)

        count = db.insert_data('a', 'A_000001.SZ_daily', df)
        assert count == 10

        result = db.get_data('a', 'A_000001.SZ_daily')
        assert len(result) == 10

    def test_insert_deduplication(self, db):
        db.create_stock_table('a', 'A_000001.SZ_daily')
        dates = pd.date_range('2024-01-01', periods=5, freq='B')
        df1 = pd.DataFrame({
            'Open': [10.0] * 5, 'High': [11.0] * 5, 'Low': [9.0] * 5,
            'Close': [10.5] * 5, 'Volume': [1000000] * 5,
            'Dividends': [0.0] * 5, 'Stock Splits': [0.0] * 5,
        }, index=dates)

        db.insert_data('a', 'A_000001.SZ_daily', df1)
        db.insert_data('a', 'A_000001.SZ_daily', df1)
        result = db.get_data('a', 'A_000001.SZ_daily')
        assert len(result) == 5

    def test_get_latest_timestamp(self, db):
        db.create_stock_table('a', 'A_000012.SZ_daily')
        dates = pd.date_range('2024-01-01', periods=5, freq='B')
        df = pd.DataFrame({
            'Open': [10.0] * 5, 'High': [11.0] * 5, 'Low': [9.0] * 5,
            'Close': [10.5] * 5, 'Volume': [1000000] * 5,
            'Dividends': [0.0] * 5, 'Stock Splits': [0.0] * 5,
        }, index=dates)

        db.insert_data('a', 'A_000012.SZ_daily', df)
        latest = db.get_latest_timestamp('a', 'A_000012.SZ_daily')
        assert latest is not None

    def test_empty_insert_returns_zero(self, db):
        df_empty = pd.DataFrame()
        count = db.insert_data('a', 'any_table', df_empty)
        assert count == 0

    def test_drop_table(self, db):
        db.create_stock_table('a', 'A_drop_test_daily')
        assert db.table_exists('a', 'A_drop_test_daily')
        db.drop_table('a', 'A_drop_test_daily')
        assert not db.table_exists('a', 'A_drop_test_daily')

    def test_unknown_market_raises(self, db):
        with pytest.raises(ValueError, match='未知市场'):
            db.get_connection('jp')
