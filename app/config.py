import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Config:
    DATA_DIR = os.path.join(BASE_DIR, 'data')
    WORKFLOWS_FILE = os.path.join(BASE_DIR, 'workflows.json')

    DB_PATHS = {
        'a': os.path.join(DATA_DIR, 'a_stock.db'),
        'hk': os.path.join(DATA_DIR, 'hk_stock.db'),
        'us': os.path.join(DATA_DIR, 'us_stock.db'),
    }

    INTERVAL_MAP = {
        'daily': {'period': '1d', 'interval': '1d'},
        '120min': {'period': '60d', 'interval': '120m'},
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
        'us': {'start': '09:30', 'end': '16:00', 'tz': 'US/Eastern'},
    }
