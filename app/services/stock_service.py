import re
from datetime import datetime
from typing import Optional
import pytz
import yfinance as yf
from app.config import Config
from app.models.database import db_manager


def detect_market(stock_input: str) -> tuple[str, str]:
    stock_input = stock_input.strip()

    if re.match(r'^[A-Za-z]{1,5}$', stock_input):
        return 'us', stock_input.upper()

    if re.match(r'^\d{5,6}$', stock_input):
        if stock_input.startswith('6') or stock_input.startswith('0') or stock_input.startswith('3'):
            return 'a', stock_input

    if re.match(r'^\d{4,5}$', stock_input):
        return 'hk', stock_input.zfill(5)

    ticker = yf.Ticker(stock_input)
    try:
        info = ticker.info
        if info and info.get('symbol'):
            symbol = info['symbol']
            if symbol.endswith('.SS') or symbol.endswith('.SZ'):
                return 'a', symbol.split('.')[0]
            elif symbol.endswith('.HK'):
                return 'hk', symbol.split('.')[0].lstrip('0')
            else:
                return 'us', symbol
    except Exception:
        pass

    raise ValueError(f"无法识别股票: {stock_input}")


def get_yfinance_ticker(market: str, stock_code: str) -> str:
    mapper = Config.YFINANCE_TICKER_MAP.get(market)
    if not mapper:
        raise ValueError(f"未知市场: {market}")
    return mapper(stock_code)


def fetch_stock_data(market: str, stock_code: str, interval: str) -> tuple:
    ticker_symbol = get_yfinance_ticker(market, stock_code)
    ticker = yf.Ticker(ticker_symbol)

    config = Config.INTERVAL_MAP[interval]
    period = config['period']
    yf_interval = config['interval']

    df = ticker.history(period=period, interval=yf_interval)
    return df


def is_trading_time(market: str) -> bool:
    trading_config = Config.TRADING_HOURS.get(market)
    if not trading_config:
        return False

    tz = pytz.timezone(trading_config['tz'])
    now = datetime.now(tz)

    if now.weekday() >= 5:
        return False

    start = datetime.strptime(trading_config['start'], '%H:%M').time()
    end = datetime.strptime(trading_config['end'], '%H:%M').time()
    current_time = now.time()

    return start <= current_time <= end


def get_table_name(stock_code: str, interval: str) -> str:
    return f"{stock_code}_{interval}"


def collect_and_store(market: str, stock_code: str, interval: str) -> int:
    if not is_trading_time(market):
        return 0

    df = fetch_stock_data(market, stock_code, interval)
    if df.empty:
        return 0

    table_name = get_table_name(stock_code, interval)
    if not db_manager.table_exists(market, table_name):
        db_manager.create_stock_table(market, table_name)

    rows_inserted = db_manager.insert_data(market, table_name, df)
    return rows_inserted
