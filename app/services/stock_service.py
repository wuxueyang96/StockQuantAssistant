import logging
import re
from datetime import datetime
from typing import List, Tuple
import pytz
import pandas as pd
import yfinance as yf
from app.config import Config
from app.models.database import db_manager

logger = logging.getLogger(__name__)
MARKET_LABEL = {'a': 'A', 'hk': 'HK', 'us': 'US'}

_akshare_available = None


def _is_akshare_available():
    global _akshare_available
    if _akshare_available is None:
        try:
            import akshare
            _akshare_available = True
        except ImportError:
            _akshare_available = False
    return _akshare_available


def format_stock_code(market: str, stock_code: str) -> str:
    if market == 'a':
        suffix = '.SS' if stock_code.startswith('6') else '.SZ'
    elif market == 'hk':
        suffix = '.HK'
    elif market == 'us':
        suffix = '.US'
    else:
        raise ValueError(f"未知市场: {market}")
    return f"{stock_code}{suffix}"


def get_workflow_id(market: str, stock_code: str, interval: str) -> str:
    code = format_stock_code(market, stock_code)
    return f"{MARKET_LABEL[market]}_{code}_{interval}"


def _detect_by_code(stock_input: str) -> List[Tuple[str, str]]:
    stock_input = stock_input.strip().upper()

    if stock_input.endswith('.SZ') or stock_input.endswith('.SS'):
        code = stock_input.rsplit('.', 1)[0]
        if re.match(r'^\d{6}$', code) and code[0] in ('6', '0', '3'):
            return [('a', code)]
        raise ValueError(f"无法识别A股代码: {stock_input}")

    if stock_input.endswith('.HK'):
        code = stock_input.rsplit('.', 1)[0]
        if re.match(r'^\d{4,5}$', code):
            return [('hk', code.zfill(5))]
        raise ValueError(f"无法识别港股代码: {stock_input}")

    if stock_input.endswith('.US'):
        code = stock_input.rsplit('.', 1)[0]
        if re.match(r'^[A-Z0-9]{1,10}$', code):
            return [('us', code.upper())]
        raise ValueError(f"无法识别美股代码: {stock_input}")

    if re.match(r'^\d{5,6}$', stock_input):
        if len(stock_input) == 6:
            if stock_input[0] in ('6', '0', '3'):
                return [('a', stock_input)]
        if len(stock_input) == 5:
            return [('hk', stock_input.zfill(5))]

    if re.match(r'^[A-Za-z]{1,5}$', stock_input):
        return [('us', stock_input.upper())]

    return []


def resolve_stock_name(name: str) -> List[Tuple[str, str]]:
    name = name.strip()

    row = db_manager.get_stock_codes(name)
    if row is None:
        raise ValueError(f"stock_codes 表中未找到 '{name}'，请先通过 POST /api/stock/code 录入该股票名称与代码映射")

    a_code, hk_code, us_code = row
    results = []
    if a_code:
        results.append(('a', a_code))
    if hk_code:
        results.append(('hk', hk_code))
    if us_code:
        results.append(('us', us_code))

    if not results:
        raise ValueError(f"stock_codes 表中 '{name}' 没有有效的市场代码")

    return results


def detect_market(stock_input: str) -> List[Tuple[str, str]]:
    results = _detect_by_code(stock_input)
    if results:
        return results
    return resolve_stock_name(stock_input)


def get_yfinance_ticker(market: str, stock_code: str) -> str:
    mapper = Config.YFINANCE_TICKER_MAP.get(market)
    if not mapper:
        raise ValueError(f"未知市场: {market}")
    return mapper(stock_code)


def _fetch_stock_data_akshare(market: str, stock_code: str, interval: str):
    import akshare as ak

    config = Config.INTERVAL_MAP[interval]
    period = config['period']

    end_date = datetime.now().strftime('%Y%m%d')

    if period == '1y':
        start_date = (datetime.now() - pd.DateOffset(years=1)).strftime('%Y%m%d')
    elif period == '6mo':
        start_date = (datetime.now() - pd.DateOffset(months=6)).strftime('%Y%m%d')
    elif period == '3mo':
        start_date = (datetime.now() - pd.DateOffset(months=3)).strftime('%Y%m%d')
    elif period == '60d':
        start_date = (datetime.now() - pd.DateOffset(days=60)).strftime('%Y%m%d')
    else:
        start_date = (datetime.now() - pd.DateOffset(years=1)).strftime('%Y%m%d')

    if interval == 'daily':
        akshare_period = 'daily'
    elif interval in ('60min', '90min', '120min'):
        akshare_period = '60'
    elif interval == '30min':
        akshare_period = '30'
    elif interval == '15min':
        akshare_period = '15'
    elif interval == '5min':
        akshare_period = '5'
    else:
        akshare_period = 'daily'

    try:
        if akshare_period == 'daily':
            df = ak.stock_zh_a_hist(
                symbol=stock_code,
                period='daily',
                start_date=start_date,
                end_date=end_date,
                adjust='qfq'
            )
        else:
            df = ak.stock_zh_a_hist(
                symbol=stock_code,
                period=akshare_period,
                start_date=start_date,
                end_date=end_date,
                adjust='qfq'
            )

        if df is None or df.empty:
            return pd.DataFrame()

        if '日期' in df.columns:
            df['日期'] = pd.to_datetime(df['日期'])
            df = df.rename(columns={
                '日期': 'Date',
                '开盘': 'Open',
                '最高': 'High',
                '最低': 'Low',
                '收盘': 'Close',
                '成交量': 'Volume',
            })
        else:
            return pd.DataFrame()

        df = df.set_index('Date')
        cols = ['Open', 'High', 'Low', 'Close']
        if 'Volume' in df.columns:
            cols.append('Volume')
        df = df[cols]
        if 'Volume' not in df.columns:
            df['Volume'] = 0
        df['Dividends'] = 0.0
        df['Stock Splits'] = 0.0
        return df
    except Exception as e:
        logger.warning(f"akshare 获取 A 股数据失败 ({stock_code}): {e}, 回退到 yfinance")
        return _fetch_stock_data_yfinance(market, stock_code, interval)


def _fetch_stock_data_yfinance(market: str, stock_code: str, interval: str):
    ticker_symbol = get_yfinance_ticker(market, stock_code)
    ticker = yf.Ticker(ticker_symbol)

    config = Config.INTERVAL_MAP[interval]
    period = config['period']
    yf_interval = config['interval']

    import io
    import sys
    old_stderr = sys.stderr
    sys.stderr = io.StringIO()
    try:
        df = ticker.history(period=period, interval=yf_interval)
    finally:
        sys.stderr = old_stderr
    return df


def fetch_stock_data(market: str, stock_code: str, interval: str):
    if market == 'a' and _is_akshare_available():
        return _fetch_stock_data_akshare(market, stock_code, interval)
    return _fetch_stock_data_yfinance(market, stock_code, interval)


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


def get_table_name(market: str, stock_code: str, interval: str) -> str:
    return get_workflow_id(market, stock_code, interval)


def collect_and_store(market: str, stock_code: str, interval: str, skip_trading_check: bool = False) -> int:
    if not skip_trading_check and not is_trading_time(market):
        return 0

    df = fetch_stock_data(market, stock_code, interval)
    if df.empty:
        return 0

    table_name = get_table_name(market, stock_code, interval)
    if not db_manager.table_exists(market, table_name):
        db_manager.create_stock_table(market, table_name)

    rows_inserted = db_manager.insert_data(market, table_name, df)
    return rows_inserted
