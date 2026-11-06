"""Loopback-only worker for QMT's Python 3.6 stdlib adapter.

Run: python -m app.qmt_bridge
Keeps original algorithms on their supported modern Python runtime.
"""
import argparse
import hmac
import json
import re
import secrets
from http.server import BaseHTTPRequestHandler, HTTPServer

import numpy as np
import pandas as pd

from app.algos.config import DEFAULT_CONFIG
from app.algos.integrated_decision import build_daily_trading_plan
from app.services.resample import resample_ohlcv

MAX_BODY = 24 * 1024 * 1024
MAX_ROWS = 150000
PERIODS = ('60min', '90min', '120min')
# Full A-share continuous auction bars, labelled by closing time.
SESSION_MINUTES = tuple(range(575, 691, 5)) + tuple(range(785, 901, 5))


def prepare_bars(payload):
    symbol = payload.get('symbol', '')
    if not isinstance(symbol, str) or not re.fullmatch(r'\d{6}\.(SH|SZ)', symbol):
        raise ValueError('Only six-digit SH/SZ A-share symbols are supported')
    cutoff_text = payload.get('cutoff', '')
    if not isinstance(cutoff_text, str) or not re.fullmatch(r'\d{14}', cutoff_text):
        raise ValueError('cutoff must be YYYYMMDDHHMMSS')
    cutoff = pd.to_datetime(cutoff_text, format='%Y%m%d%H%M%S')
    if cutoff.hour != 15 or cutoff.minute != 0 or cutoff.second != 0:
        raise ValueError('cutoff must be a closed-day 15:00:00 boundary')
    expected = payload.get('expected_session', '')
    if not isinstance(expected, str) or not re.fullmatch(r'\d{8}', expected):
        raise ValueError('expected_session from QMT exchange calendar is required')
    expected_day = pd.to_datetime(expected, format='%Y%m%d')
    if expected_day > cutoff.normalize() or (cutoff.normalize() - expected_day).days > 15:
        raise ValueError('Invalid or stale exchange calendar; refresh benchmark history')
    rows = payload.get('bars')
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_ROWS:
        raise ValueError('bars must contain 1..150000 rows')
    if any(not isinstance(row, list) or len(row) != 6 for row in rows):
        raise ValueError('Each bar must be [timestamp, open, high, low, close, volume]')
    df = pd.DataFrame(rows, columns=['timestamp', 'Open', 'High', 'Low', 'Close', 'Volume'])
    if not df.timestamp.map(lambda x: isinstance(x, str) and bool(re.fullmatch(r'\d{14}', x))).all():
        raise ValueError('Bar timestamps must be YYYYMMDDHHMMSS')
    df.index = pd.to_datetime(df.pop('timestamp'), format='%Y%m%d%H%M%S')
    # Defense in depth: provider/end_time bugs cannot leak future bars.
    df = df.loc[df.index <= cutoff].sort_index()
    if df.empty or df.index.has_duplicates:
        raise ValueError('Empty or duplicate bar timestamps')
    if df.index[-1].strftime('%Y%m%d') != expected:
        raise ValueError('Stale or suspended: latest bar does not match completed exchange session ' + expected)
    df = df.apply(pd.to_numeric, errors='raise')
    if not np.isfinite(df.to_numpy(dtype=float)).all():
        raise ValueError('Non-finite OHLCV')
    if ((df[['Open', 'High', 'Low', 'Close']] <= 0).any().any()
            or (df.Volume < 0).any()
            or (df.High < df[['Open', 'Close', 'Low']].max(axis=1)).any()
            or (df.Low > df[['Open', 'Close', 'High']].min(axis=1)).any()):
        raise ValueError('Invalid OHLCV ranges')
    # Original resampler buckets by sequence, so missing intraday bars would
    # silently shift boundaries. Reject rather than invent/fill history.
    for day, group in df.groupby(df.index.date):
        minutes = tuple(group.index.hour * 60 + group.index.minute)
        if minutes != SESSION_MINUTES or any(group.index.second):
            raise ValueError('Incomplete/nonstandard A-share session on ' + str(day))
    daily = resample_ohlcv(df, 'daily')
    if len(daily) < DEFAULT_CONFIG.long_period + 1:
        raise ValueError('Need at least %d complete trading days' % (DEFAULT_CONFIG.long_period + 1))
    intraday = {period: resample_ohlcv(df, period) for period in PERIODS}
    return symbol, cutoff, df, daily, intraday


def analyze_payload(payload):
    if not isinstance(payload, dict):
        raise ValueError('Expected a JSON object')
    symbol, cutoff, df, daily, intraday = prepare_bars(payload)
    plan = build_daily_trading_plan(daily, intraday, symbol=symbol).to_api_dict()
    return {
        'status': 'ok', 'read_only': True, 'symbol': symbol,
        'engine': 'build_daily_trading_plan',
        'cutoff': cutoff.isoformat(), 'last_bar': df.index[-1].isoformat(),
        'trading_days': len(daily), 'adjustment': 'none',
        'position_source': 'original_algorithm_previous_trend_proxy_not_account',
        'plan': plan,
        'warnings': [
            'No account position was read. actual_position is the original previous-trend proxy (or zero), not a holding. Target position is an analysis scale (0..10), not shares.',
            'execute_date is the original weekday estimate, not an exchange holiday calendar.',
            'Unadjusted prices preserve point-in-time data; corporate actions can distort signals.',
            'This is signal analysis only, not QMT order execution or a performance backtest.',
        ],
    }


def make_handler(token):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path != '/analyze':
                self.send_error(404)
                return
            supplied = self.headers.get('X-StockQuant-Token', '')
            if not hmac.compare_digest(supplied, token):
                self.send_error(403)
                return
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= MAX_BODY:
                    raise ValueError('Invalid request size')
                payload = json.loads(self.rfile.read(size))
                result = analyze_payload(payload)
                body = json.dumps(result, ensure_ascii=False, allow_nan=False).encode('utf-8')
                status = 200
            except (ValueError, TypeError, KeyError, OverflowError) as exc:
                body = json.dumps({'status': 'error', 'error': str(exc)}).encode('utf-8')
                status = 400
            except Exception:
                body = b'{"status":"error","error":"Analysis failed; inspect worker runtime"}'
                status = 500
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def setup(self):
            super().setup()
            self.connection.settimeout(90)

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    token = secrets.token_hex(24)
    server = HTTPServer(('127.0.0.1', 8765), make_handler(token))
    print('Read-only QMT bridge at http://127.0.0.1:8765', flush=True)
    print('Set BRIDGE_TOKEN in QMT to: ' + token, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
