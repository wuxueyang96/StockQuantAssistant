# -*- coding: utf-8 -*-
"""Full QMT embedded Python 3.6 entrypoint. Read-only; no account or orders.

Copy this single file into the QMT Python editor. Run the companion worker
with modern Python first. See docs/qmt.md. No project imports in QMT.
"""
import datetime
import json
import math
import re
import time
import urllib.request

SYMBOL = '600000.SH'
HISTORY_START = '20230101'
BRIDGE_URL = 'http://127.0.0.1:8765/analyze'
# Match the randomly generated token printed by the worker at startup.
BRIDGE_TOKEN = ''
TIMEOUT_SECONDS = 60
RETRY_SECONDS = 60
_FIELDS = ['open', 'high', 'low', 'close', 'volume']
_STATE = {}


def init(ContextInfo):
    if not re.match(r'^\d{6}\.(SH|SZ)$', SYMBOL):
        raise ValueError('Set SYMBOL to an A-share code, e.g. 600000.SH')
    if not BRIDGE_TOKEN:
        raise ValueError('Start the local worker and set BRIDGE_TOKEN first')
    if BRIDGE_URL != 'http://127.0.0.1:8765/analyze':
        raise ValueError('Only the fixed loopback worker endpoint is supported')
    _STATE.clear()
    print('StockQuant read-only bridge: no orders, no account access')


def _timestamp(value):
    # get_market_data_ex documents YYYYMMDDHHMMSS string indices.
    # Some releases return datetime or Unix-millisecond indices instead.
    if hasattr(value, 'strftime'):
        return value.strftime('%Y%m%d%H%M%S')
    value = str(value)
    if re.match(r'^\d{14}$', value):
        datetime.datetime.strptime(value, '%Y%m%d%H%M%S')
        return value
    if re.match(r'^\d{13}$', value):
        dt = datetime.datetime.utcfromtimestamp(int(value) / 1000.0)
        return (dt + datetime.timedelta(hours=8)).strftime('%Y%m%d%H%M%S')
    raise ValueError('Unsupported QMT timestamp: ' + value)


def _rows(frame, cutoff):
    rows = []
    for index, row in frame.iterrows():
        stamp = _timestamp(index)
        if stamp > cutoff:
            continue
        values = [float(row[field]) for field in _FIELDS]
        if not all(math.isfinite(v) for v in values):
            raise ValueError('Invalid OHLCV at ' + stamp)
        rows.append([stamp] + values)
    return rows


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Bridge redirects are forbidden')


def _request(payload):
    data = json.dumps(payload, allow_nan=False).encode('utf-8')
    req = urllib.request.Request(BRIDGE_URL, data=data, headers={
        'Content-Type': 'application/json', 'X-StockQuant-Token': BRIDGE_TOKEN})
    # Disable proxies explicitly so local data never traverses an HTTP proxy.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    with opener.open(req, timeout=TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode('utf-8'))


def handlebar(ContextInfo):
    # Milliseconds -> China exchange local time, independent of OS timezone.
    stamp = ContextInfo.get_bar_timetag(ContextInfo.barpos)
    current = datetime.datetime.utcfromtimestamp(stamp / 1000.0)
    current += datetime.timedelta(hours=8)
    # Conservatively use only days BEFORE the callback date, including in
    # historical replay. Never consume an unfinished daily bar or wall clock.
    cutoff = (current.date() - datetime.timedelta(days=1)).strftime('%Y%m%d') + '150000'
    if _STATE.get('done') == cutoff:
        return
    now = time.monotonic()
    if _STATE.get('attempt') == cutoff and now - _STATE.get('at', 0) < RETRY_SECONDS:
        return
    _STATE.update(attempt=cutoff, at=now)
    try:
        # Use the exchange benchmark calendar, not this stock's cached bars.
        dates = ContextInfo.get_trading_dates('000001.SH', '', cutoff[:8], 1, '1d')
        if not dates or not re.match(r'^\d{8}$', str(dates[-1])):
            raise ValueError('Cannot verify latest completed exchange session')
        expected = str(dates[-1])
        if expected > cutoff[:8]:
            raise ValueError('Calendar returned a future session')
        data = ContextInfo.get_market_data_ex(
            _FIELDS, [SYMBOL], period='5m', start_time=HISTORY_START,
            end_time=cutoff, count=-1, dividend_type='none',
            fill_data=False, subscribe=False)
        frame = data.get(SYMBOL)
        if frame is None or len(frame) == 0:
            raise ValueError('No local 5m data; download history in QMT first')
        result = _request({'symbol': SYMBOL, 'cutoff': cutoff,
                           'expected_session': expected, 'bars': _rows(frame, cutoff)})
        if result.get('status') != 'ok':
            raise ValueError(str(result))
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        _STATE['done'] = cutoff
    except Exception as exc:
        # Fail closed: no substitute indicator and no stale plan emitted.
        print('StockQuant analysis unavailable: ' + str(exc))
