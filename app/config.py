import os


def _get_data_dir():
    env = os.environ.get('STOCKQUANT_DATA_DIR')
    if env:
        return env
    return os.path.join(os.path.expanduser('~'), '.stockquant', 'data')


class Config:
    DATA_DIR = _get_data_dir()

    OSS_BUCKET = os.environ.get('OSS_BUCKET')
    OSS_ENDPOINT = os.environ.get('OSS_ENDPOINT')
    OSS_REGION = os.environ.get('OSS_REGION', 'us-east-1')
    OSS_ACCESS_KEY_ID = os.environ.get('OSS_ACCESS_KEY_ID')
    OSS_ACCESS_KEY_SECRET = os.environ.get('OSS_ACCESS_KEY_SECRET')

    METADATA_DB_PATH = os.path.join(DATA_DIR, 'metadata.db')

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
        'hk': lambda code: f"{int(code):04d}.HK",
        'us': lambda code: code,
    }

    TRADING_HOURS = {
        'a': {'start': '09:30', 'end': '15:00', 'tz': 'Asia/Shanghai'},
        'hk': {'start': '09:30', 'end': '16:00', 'tz': 'Asia/Hong_Kong'},
        'us': {'start': '09:30', 'end': '16:00', 'tz': 'America/New_York'},
    }
