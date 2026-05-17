"""GET /api/stock/chart 图表 API 测试。

契约：
- 返回 image/png；
- 图内含 K 线 + 4 条趋势通道线（short_upper/short_lower/long_upper/long_lower）；
- 默认渲染最近 120 根；
- 支持 query 参数 stock / interval / bars。
"""
import numpy as np
import pandas as pd
import pytest


def _make_uptrend_5min(n_days: int = 120) -> pd.DataFrame:
    dates = pd.bdate_range('2024-01-01', periods=n_days)
    am = pd.timedelta_range(start='9:30:00', periods=24, freq='5min')
    pm = pd.timedelta_range(start='13:00:00', periods=24, freq='5min')
    idx = []
    for d in dates:
        for off in am:
            idx.append(d + off)
        for off in pm:
            idx.append(d + off)
    idx = pd.DatetimeIndex(idx)
    n = len(idx)
    closes = np.linspace(50.0, 150.0, n)
    df = pd.DataFrame({
        'timestamp': idx,
        'open': closes,
        'high': closes * 1.01,
        'low': closes * 0.99,
        'close': closes,
        'volume': [1_000_000] * n,
    })
    return df


class TestChartEndpoint:
    @pytest.fixture(autouse=True)
    def setup(self, app, seed_stock_codes):
        from app.models.database import db_manager
        self.db = db_manager
        df = _make_uptrend_5min(n_days=120)
        db_manager.insert_data('a', 'A_000001.SZ_5min', df)

    def test_chart_returns_png(self, client):
        resp = client.get('/api/stock/chart?stock=000001&interval=daily&mode=single')
        assert resp.status_code == 200, resp.get_data(as_text=True)
        assert resp.mimetype == 'image/png'
        body = resp.get_data()
        # PNG 魔数 89 50 4E 47 0D 0A 1A 0A
        assert body[:8] == b'\x89PNG\r\n\x1a\n'
        assert len(body) > 1000  # 至少有像样的大小

    def test_chart_supports_intervals(self, client):
        for itv in ('daily', '120min', '90min', '60min'):
            resp = client.get(f'/api/stock/chart?stock=000001&interval={itv}&mode=single')
            assert resp.status_code == 200, f'{itv} failed: {resp.get_data(as_text=True)}'
            assert resp.mimetype == 'image/png'

    def test_chart_bars_query_param(self, client):
        """bars 控制最近 N 根 K 线渲染窗口。"""
        resp = client.get('/api/stock/chart?stock=000001&interval=daily&bars=60&mode=single')
        assert resp.status_code == 200
        assert resp.mimetype == 'image/png'

    def test_chart_missing_stock(self, client):
        resp = client.get('/api/stock/chart')
        assert resp.status_code == 400
        body = resp.get_json()
        assert body['success'] is False
        assert 'stock' in body['message']

    def test_chart_invalid_interval(self, client):
        resp = client.get('/api/stock/chart?stock=000001&interval=7min&mode=single')
        assert resp.status_code == 400
        body = resp.get_json()
        assert body['success'] is False

    def test_chart_no_data_returns_404(self, client):
        resp = client.get('/api/stock/chart?stock=00700&interval=daily&mode=single')
        # 没注册 / 没数据 → 404
        assert resp.status_code == 404

    def test_chart_integrated_default_returns_taller_png(self, client):
        """默认 mode=integrated：日线 + 60/90/120 MACD 纵向拼接，体积明显大于单图。"""
        r_int = client.get('/api/stock/chart?stock=000001')
        r_single = client.get('/api/stock/chart?stock=000001&mode=single&interval=daily')
        assert r_int.status_code == 200 and r_single.status_code == 200
        assert len(r_int.get_data()) > len(r_single.get_data()) * 1.5

    def test_chart_mode_single_explicit(self, client):
        resp = client.get('/api/stock/chart?stock=000001&mode=single&interval=daily')
        r_int = client.get('/api/stock/chart?stock=000001')
        assert resp.status_code == 200
        assert len(resp.get_data()) * 1.5 < len(r_int.get_data())

    def test_chart_invalid_mode(self, client):
        resp = client.get('/api/stock/chart?stock=000001&mode=weird')
        assert resp.status_code == 400


class TestChartService:
    """单元测：纯 OHLCV DataFrame + 通道值字典 → PNG bytes。"""

    def test_render_chart_returns_png_bytes(self):
        from app.services.chart_service import render_chart_png
        df = _make_uptrend_5min(n_days=120)
        df = df.set_index('timestamp')
        df = df.rename(columns={c: c.capitalize() for c in df.columns})

        png = render_chart_png(
            df=df,
            title='测试',
            channels_df=None,  # channels 可以从 df 算出，service 内部处理
        )
        assert isinstance(png, (bytes, bytearray))
        assert png[:8] == b'\x89PNG\r\n\x1a\n'
        assert len(png) > 1000
