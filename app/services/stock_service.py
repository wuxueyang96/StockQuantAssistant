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
        suffix = '.SS' if stock_code.startswith(('5', '6')) else '.SZ'
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


def _is_etf(stock_code: str) -> bool:
    return stock_code.startswith('5')


def _detect_by_code(stock_input: str) -> List[Tuple[str, str]]:
    stock_input = stock_input.strip().upper()

    if stock_input.endswith('.SZ') or stock_input.endswith('.SS'):
        code = stock_input.rsplit('.', 1)[0]
        if re.match(r'^\d{6}$', code) and code[0] in ('6', '0', '3', '5'):
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
            if stock_input[0] in ('6', '0', '3', '5'):
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


def _fetch_5m_akshare_a(stock_code: str) -> pd.DataFrame:
    import akshare as ak
    end_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    start_date = (datetime.now() - pd.DateOffset(days=60)).strftime('%Y-%m-%d %H:%M:%S')
    df = ak.stock_zh_a_hist_min_em(
        symbol=stock_code,
        period='5',
        start_date=start_date,
        end_date=end_date,
        adjust='qfq',
    )
    return _normalize_akshare_min(df, tz='Asia/Shanghai')


def _fetch_5m_akshare_etf(stock_code: str) -> pd.DataFrame:
    import akshare as ak
    end_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    start_date = (datetime.now() - pd.DateOffset(days=60)).strftime('%Y-%m-%d %H:%M:%S')
    df = ak.fund_etf_hist_min_em(
        symbol=stock_code,
        period='5',
        start_date=start_date,
        end_date=end_date,
        adjust='qfq',
    )
    return _normalize_akshare_min(df, tz='Asia/Shanghai')


def _fetch_5m_akshare_hk(stock_code: str) -> pd.DataFrame:
    import akshare as ak
    end_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    start_date = (datetime.now() - pd.DateOffset(days=60)).strftime('%Y-%m-%d %H:%M:%S')
    df = ak.stock_hk_hist_min_em(
        symbol=stock_code,
        period='5',
        start_date=start_date,
        end_date=end_date,
        adjust='qfq',
    )
    return _normalize_akshare_min(df, tz='Asia/Hong_Kong')


def _fetch_5m_yfinance(market: str, stock_code: str) -> pd.DataFrame:
    ticker_symbol = get_yfinance_ticker(market, stock_code)
    logger.info(f"yfinance 拉取: {ticker_symbol} interval=5m")
    ticker = yf.Ticker(ticker_symbol)

    import io
    import sys
    old_stderr = sys.stderr
    stderr_buf = io.StringIO()
    sys.stderr = stderr_buf
    try:
        df = ticker.history(period='60d', interval='5m')
    finally:
        sys.stderr = old_stderr
        stderr_content = stderr_buf.getvalue()
        if stderr_content.strip():
            logger.warning(f"yfinance stderr ({ticker_symbol}): {stderr_content.strip()}")

    if df is None or df.empty:
        logger.warning(f"yfinance 返回空数据: {ticker_symbol}")
        return pd.DataFrame()
    logger.info(f"yfinance 获取 {ticker_symbol} 数据 {len(df)} 行")
    return df


def _normalize_akshare_min(df, tz: str) -> pd.DataFrame:
    """akshare 分钟线返回中文列 + 时间字符串，统一转 OHLCV + tz-aware 索引。"""
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.rename(columns={
        '时间': 'Date',
        '开盘': 'Open',
        '最高': 'High',
        '最低': 'Low',
        '收盘': 'Close',
        '成交量': 'Volume',
    })
    if 'Date' not in df.columns:
        return pd.DataFrame()
    df['Date'] = pd.to_datetime(df['Date'])
    try:
        df['Date'] = df['Date'].dt.tz_localize(tz)
    except TypeError:
        df['Date'] = df['Date'].dt.tz_convert(tz)
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


def fetch_stock_data(market: str, stock_code: str, interval: str = '5min'):
    """统一拉取 5min K 线（采集层最细粒度），其他周期由 resample 运行时合成。

    保留 `interval` 形参以兼容旧调用，但实际上只会拉 5min。
    """
    if interval != '5min':
        logger.info(
            f"采集只支持 5min（请求 interval={interval} 将忽略，请在决策层用 resample 合成）"
        )

    if market == 'a' and _is_akshare_available():
        try:
            if _is_etf(stock_code):
                return _fetch_5m_akshare_etf(stock_code)
            return _fetch_5m_akshare_a(stock_code)
        except Exception as e:
            logger.warning(f"akshare A 股 5m 失败 ({stock_code}): {e}，回退 yfinance")
            return _fetch_5m_yfinance(market, stock_code)

    if market == 'hk' and _is_akshare_available():
        try:
            return _fetch_5m_akshare_hk(stock_code)
        except Exception as e:
            logger.warning(f"akshare 港股 5m 失败 ({stock_code}): {e}，回退 yfinance")
            return _fetch_5m_yfinance(market, stock_code)

    # 美股 / fallback
    return _fetch_5m_yfinance(market, stock_code)


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


def collect_and_store(market: str, stock_code: str, interval: str = '5min',
                      skip_trading_check: bool = False) -> int:
    """统一采集 5min K 线写入 `*_5min` 表。

    `interval` 参数保留为兼容形参；实际无论传什么都只采 5min。高粒度由
    `app.services.resample` 在决策时按需合成。
    """
    if not skip_trading_check and not is_trading_time(market):
        return 0

    df = fetch_stock_data(market, stock_code, '5min')
    if df is None or df.empty:
        logger.warning(f"未获取到 5min 数据: {market}/{stock_code}")
        return 0

    table_name = get_table_name(market, stock_code, '5min')
    if not db_manager.table_exists(market, table_name):
        db_manager.create_stock_table(market, table_name)

    rows_inserted = db_manager.insert_data(market, table_name, df)
    logger.info(f"写入 {rows_inserted} 条 5min 数据到 {table_name}")
    return rows_inserted
