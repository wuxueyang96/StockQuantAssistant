import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Config:
    DATA_DIR = os.path.join(BASE_DIR, 'data')
    METADATA_DB_PATH = os.path.join(DATA_DIR, 'metadata.db')

    DB_PATHS = {
        'a': os.path.join(DATA_DIR, 'a_stock.db'),
        'hk': os.path.join(DATA_DIR, 'hk_stock.db'),
        'us': os.path.join(DATA_DIR, 'us_stock.db'),
    }

    # yfinance 支持的 interval: 1m,2m,5m,15m,30m,60m,90m,1h,4h,1d,5d,1wk,1mo,3mo
    # 120m 不被支持，映射到 1h（60m）作为最接近可用粒度
    INTERVAL_MAP = {
        'daily': {'period': '1y', 'interval': '1d'},
        '120min': {'period': '60d', 'interval': '1h'},
        '90min': {'period': '60d', 'interval': '90m'},
        '60min': {'period': '60d', 'interval': '60m'},
    }

    INTERVAL_MINUTES = {
        'daily': 24 * 60,
        '120min': 120,
        '90min': 90,
        '60min': 60,
    }

    YFINANCE_TICKER_MAP = {
        'a': lambda code: f"{code}.SS" if code.startswith('6') else f"{code}.SZ",
        'hk': lambda code: f"{code}.HK",
        'us': lambda code: code,
    }

    TRADING_HOURS = {
        'a': {'start': '09:30', 'end': '15:00', 'tz': 'Asia/Shanghai'},
        'hk': {'start': '09:30', 'end': '16:00', 'tz': 'Asia/Hong_Kong'},
        'us': {'start': '09:30', 'end': '16:00', 'tz': 'America/New_York'},
    }
