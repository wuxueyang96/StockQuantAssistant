import os
import sys
import tempfile
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

os.environ['FLASK_TESTING'] = '1'


@pytest.fixture
def temp_db_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def app(temp_db_dir):
    from app.config import Config
    Config.DATA_DIR = temp_db_dir
    Config.METADATA_DB_PATH = os.path.join(temp_db_dir, 'metadata.db')
    Config.DB_PATHS = {
        'a': os.path.join(temp_db_dir, 'a_stock.db'),
        'hk': os.path.join(temp_db_dir, 'hk_stock.db'),
        'us': os.path.join(temp_db_dir, 'us_stock.db'),
    }

    from app import create_app
    application = create_app()
    application.config['TESTING'] = True
    yield application

    from app.models.database import db_manager
    db_manager.close_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def seed_stock_codes(app):
    from app.models.database import db_manager
    db_manager.upsert_stock_code('阿里巴巴', hk_code='09988', us_code='BABA')
    db_manager.upsert_stock_code('贵州茅台', a_code='600519')
    db_manager.upsert_stock_code('小米', hk_code='01810')
    db_manager.upsert_stock_code('苹果', us_code='AAPL')


@pytest.fixture
def clean_db(app, temp_db_dir):
    from app.models.database import db_manager
    db_manager._connections.clear()
    yield db_manager
    db_manager.close_all()
    db_manager._connections.clear()


@pytest.fixture
def mock_stock_data():
    dates = pd.date_range(end=pd.Timestamp.now(), periods=300, freq='B')
    np = pytest.importorskip('numpy')
    df = pd.DataFrame({
        'Open': np.random.uniform(10, 100, 300),
        'High': np.random.uniform(10, 100, 300),
        'Low': np.random.uniform(10, 100, 300),
        'Close': np.random.uniform(10, 100, 300),
        'Volume': np.random.randint(1000, 1000000, 300),
        'Dividends': [0.0] * 300,
        'Stock Splits': [0.0] * 300,
    }, index=dates)
    df['High'] = df[['Open', 'High', 'Close']].max(axis=1)
    df['Low'] = df[['Open', 'Low', 'Close']].min(axis=1)
    return df
