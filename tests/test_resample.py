"""5min K 线 → 60/90/120min/daily 合成测试。

合成规则（见 docs/algorithm.md §二.5 与 docs/design.md）：
- 按 **交易日** 分组（跨日不合并）；
- 按"日内累计 K 线序号"切分（跨午休按序号连续，符合 A 股一天 48 根 5m 的结构）；
- OHLCV 聚合：Open=first, High=max, Low=min, Close=last, Volume=sum；
- 桶不足时仍输出（最后一根尾巴允许 < N 根）。
"""
import numpy as np
import pandas as pd
import pytest


def _make_a_share_day(date_str: str, base: float = 100.0) -> pd.DataFrame:
    """构造 A 股一日 48 根 5min K 线，价格从 base 线性升到 base+47."""
    am = pd.date_range(f'{date_str} 09:30', f'{date_str} 11:25', freq='5min', tz='Asia/Shanghai')
    pm = pd.date_range(f'{date_str} 13:00', f'{date_str} 14:55', freq='5min', tz='Asia/Shanghai')
    idx = am.append(pm)
    n = len(idx)
    closes = np.linspace(base, base + n - 1, n)
    return pd.DataFrame({
        'Open': closes,
        'High': closes + 0.5,
        'Low': closes - 0.5,
        'Close': closes,
        'Volume': [1000] * n,
    }, index=idx)


def _make_us_day(date_str: str, base: float = 100.0) -> pd.DataFrame:
    """构造美股一日 78 根 5min（9:30-15:55）连续。"""
    idx = pd.date_range(f'{date_str} 09:30', f'{date_str} 15:55', freq='5min', tz='America/New_York')
    n = len(idx)
    closes = np.linspace(base, base + n - 1, n)
    return pd.DataFrame({
        'Open': closes, 'High': closes + 0.5, 'Low': closes - 0.5, 'Close': closes,
        'Volume': [1000] * n,
    }, index=idx)


class TestResampleBasic:
    def test_aggregates_ohlcv_per_bucket(self):
        from app.services.resample import resample_ohlcv
        df = _make_a_share_day('2024-01-02', base=100.0)
        out = resample_ohlcv(df, '60min')
        # A 股一天 48 根 5m → 60min 每根 12 根 5m → 一天 4 根 60m
        assert len(out) == 4
        first = out.iloc[0]
        # 桶 1 包含 5m idx 0..11 → close 100..111
        assert first['Open'] == pytest.approx(100.0)
        assert first['High'] == pytest.approx(111.5)   # close+0.5 的 max
        assert first['Low'] == pytest.approx(99.5)
        assert first['Close'] == pytest.approx(111.0)
        assert first['Volume'] == 12 * 1000

    def test_120min_two_buckets_a_share(self):
        from app.services.resample import resample_ohlcv
        df = _make_a_share_day('2024-01-02', base=100.0)
        out = resample_ohlcv(df, '120min')
        # 48 根 5m / 24 = 2 根 120m
        assert len(out) == 2

    def test_90min_three_buckets_a_share(self):
        from app.services.resample import resample_ohlcv
        df = _make_a_share_day('2024-01-02', base=100.0)
        out = resample_ohlcv(df, '90min')
        # 48 / 18 = 2 完整 + 12 根余 → 3 根（最后一根 12 根 5m = 60 分钟）
        assert len(out) == 3

    def test_daily_aggregates_full_day(self):
        from app.services.resample import resample_ohlcv
        df = _make_a_share_day('2024-01-02', base=100.0)
        out = resample_ohlcv(df, 'daily')
        assert len(out) == 1
        row = out.iloc[0]
        assert row['Open'] == pytest.approx(100.0)
        assert row['Close'] == pytest.approx(147.0)
        assert row['High'] == pytest.approx(147.5)
        assert row['Low'] == pytest.approx(99.5)
        assert row['Volume'] == 48 * 1000


class TestResampleMultiDay:
    def test_buckets_do_not_cross_days(self):
        from app.services.resample import resample_ohlcv
        df1 = _make_a_share_day('2024-01-02', base=100.0)
        df2 = _make_a_share_day('2024-01-03', base=200.0)
        df = pd.concat([df1, df2]).sort_index()
        out = resample_ohlcv(df, '60min')
        # 两天，每天 4 根 → 8 根
        assert len(out) == 8
        # 第一天最后一根（11..47 的第 4 桶）close 应在 144..147 范围（同日）
        day1 = out[out.index.date == pd.Timestamp('2024-01-02').date()]
        day2 = out[out.index.date == pd.Timestamp('2024-01-03').date()]
        assert len(day1) == 4 and len(day2) == 4

    def test_us_market_one_day_resample(self):
        from app.services.resample import resample_ohlcv
        df = _make_us_day('2024-01-02', base=50.0)
        out = resample_ohlcv(df, '60min')
        # 78 根 5m / 12 = 6 完整桶 + 6 根余 → 7 根
        assert len(out) == 7
        out120 = resample_ohlcv(df, '120min')
        # 78 / 24 = 3 完整 + 6 → 4 根
        assert len(out120) == 4

    def test_idempotent_when_already_target_interval(self):
        from app.services.resample import resample_ohlcv
        df = _make_a_share_day('2024-01-02')
        out = resample_ohlcv(df, '5min')
        # 5min → 5min 应是 identity（rows 相同）
        assert len(out) == len(df)


class TestResampleEdge:
    def test_empty_input(self):
        from app.services.resample import resample_ohlcv
        empty = pd.DataFrame(columns=['Open', 'High', 'Low', 'Close', 'Volume'])
        out = resample_ohlcv(empty, '60min')
        assert len(out) == 0

    def test_partial_last_bucket_preserved(self):
        """日内不足 N 根 5m 的尾部应仍输出一根（< N 根 5m 合成）。"""
        from app.services.resample import resample_ohlcv
        df = _make_a_share_day('2024-01-02').iloc[:5]  # 仅 5 根 5m
        out = resample_ohlcv(df, '60min')
        assert len(out) == 1
        assert out.iloc[0]['Volume'] == 5 * 1000

    def test_invalid_interval(self):
        from app.services.resample import resample_ohlcv
        df = _make_a_share_day('2024-01-02')
        with pytest.raises(ValueError):
            resample_ohlcv(df, '7min')
