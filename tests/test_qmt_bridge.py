"""Offline contracts; these are not a substitute for the broker terminal test."""
import ast
import copy
import datetime
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from app.qmt_bridge import analyze_payload, prepare_bars, SESSION_MINUTES
from app.algos.integrated_decision import build_daily_trading_plan

ROOT = Path(__file__).resolve().parents[1]


def fixture_payload():
    bars = []
    for i, day in enumerate(pd.bdate_range('2024-01-02', periods=95)):
        for j, minute in enumerate(SESSION_MINUTES):
            stamp = day + pd.Timedelta(minutes=minute)
            close = 10 + i * .03 + j * .001
            bars.append([stamp.strftime('%Y%m%d%H%M%S'), close, close + .1,
                         close - .1, close + .01, 100.0])
    return {'symbol': '600000.SH', 'cutoff': bars[-1][0], 'expected_session': bars[-1][0][:8], 'bars': bars}


@pytest.fixture(scope='module')
def payload():
    return fixture_payload()


def load_adapter():
    spec = importlib.util.spec_from_file_location('qmt_adapter_test', ROOT / 'qmt/stockquant_strategy.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_core_plan_exact_parity(payload):
    symbol, _, _, daily, intra = prepare_bars(payload)
    expected = build_daily_trading_plan(daily, intra, symbol=symbol).to_api_dict()
    result = analyze_payload(payload)
    assert result['plan'] == expected
    assert result['read_only'] is True
    assert result['position_source'] == 'original_algorithm_previous_trend_proxy_not_account'
    json.dumps(result, allow_nan=False)


def test_future_bars_do_not_change_plan(payload):
    with_future = copy.deepcopy(payload)
    with_future['bars'].append(['20990101093500', 1, 2, 1, 2, 1])
    assert analyze_payload(with_future) == analyze_payload(payload)


@pytest.mark.parametrize('kind', ['missing', 'duplicate', 'nan', 'bad_ohlc', 'warmup', 'stamp', 'stale'])
def test_bad_data_fails_closed(payload, kind):
    data = copy.deepcopy(payload)
    if kind == 'missing':
        data['bars'].pop(5)
    elif kind == 'duplicate':
        data['bars'].append(data['bars'][0])
    elif kind == 'nan':
        data['bars'][0][1] = float('nan')
    elif kind == 'bad_ohlc':
        data['bars'][0][2] = 1
    elif kind == 'warmup':
        data['bars'] = data['bars'][:48]
    elif kind == 'stale':
        data['bars'] = data['bars'][:-48]
    else:
        data['bars'][0][0] = 'not a date'
    with pytest.raises(ValueError):
        analyze_payload(data)


def test_adapter_python36_syntax_and_stdlib_only():
    source = (ROOT / 'qmt/stockquant_strategy.py').read_text()
    tree = ast.parse(source, feature_version=(3, 6))
    imports = [node.names[0].name for node in ast.walk(tree) if isinstance(node, ast.Import)]
    assert set(imports) <= {'datetime', 'json', 'math', 're', 'time', 'urllib.request'}
    forbidden = {'passorder', 'order_shares', 'order_target_percent', 'get_trade_detail_data'}
    assert not any(isinstance(node, ast.Call) and
                   ((isinstance(node.func, ast.Name) and node.func.id in forbidden) or
                    (isinstance(node.func, ast.Attribute) and node.func.attr in forbidden))
                   for node in ast.walk(tree))


def test_adapter_callback_cutoff_dedup_and_retry(monkeypatch):
    module = load_adapter()
    module.BRIDGE_TOKEN = 'test'
    calls = []
    # 2024-06-03 10:00 China time, even on a host in UTC.
    stamp = int(datetime.datetime(2024, 6, 3, 2, tzinfo=datetime.timezone.utc).timestamp() * 1000)
    df = pd.DataFrame([[10, 11, 9, 10, 100]],
                      columns=module._FIELDS, index=['20240531150000'])
    def read(*args, **kwargs):
        calls.append(kwargs)
        return {module.SYMBOL: df}
    context = SimpleNamespace(barpos=0, get_bar_timetag=lambda pos: stamp, get_market_data_ex=read,
                              get_trading_dates=lambda *args: ['20240531'])
    module.init(context)
    posted = []
    def request(data):
        posted.append(data)
        return {'status': 'ok'}
    monkeypatch.setattr(module, '_request', request)
    module.handlebar(context)
    module.handlebar(context)
    assert len(posted) == 1
    assert posted[0]['cutoff'] == '20240602150000'
    assert calls[0]['subscribe'] is False
    assert calls[0]['fill_data'] is False
    assert calls[0]['dividend_type'] == 'none'
    assert calls[0]['end_time'] == posted[0]['cutoff']
    module.init(context)
    monkeypatch.setattr(module, '_request', lambda data: (_ for _ in ()).throw(ValueError('offline')))
    module.handlebar(context)
    assert 'done' not in module._STATE
    module.handlebar(context)
    assert len(calls) == 2  # bounded retry, not every tick


def test_adapter_redirect_is_blocked():
    module = load_adapter()
    with pytest.raises(ValueError):
        module._NoRedirect().redirect_request(None, None, 302, 'Found', {}, 'http://example.com')
