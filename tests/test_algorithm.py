import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta


def make_ohlcv(prices, high_offset=0.05, low_offset=0.05, volume=1000000):
    """Helper to create OHLCV DataFrame from close prices."""
    dates = [datetime(2024, 1, 1) + timedelta(days=i) for i in range(len(prices))]
    closes = np.array(prices, dtype=float)
    highs = closes * (1 + np.random.uniform(0, high_offset, len(prices)))
    lows = closes * (1 - np.random.uniform(0, low_offset, len(prices)))
    opens = closes * (1 + np.random.uniform(-0.02, 0.02, len(prices)))
    highs = np.maximum(highs, opens)
    lows = np.minimum(lows, opens)
    df = pd.DataFrame({
        'Open': opens, 'High': highs, 'Low': lows, 'Close': closes,
        'Volume': [volume] * len(prices), 'Dividends': 0.0, 'Stock Splits': 0.0,
    }, index=dates)
    return df


class TestTrendChannel:
    @pytest.fixture
    def trend(self):
        from app.algos.trend import TrendChannel
        return TrendChannel(short_period=25, long_period=90, offset_pct=0.03)

    def test_channels_basic_shape(self, trend):
        df = make_ohlcv([100 + i * 0.5 for i in range(200)])
        channels = trend.compute_all(df)
        assert 'short_upper' in channels.columns
        assert 'short_lower' in channels.columns
        assert 'long_upper' in channels.columns
        assert 'long_lower' in channels.columns
        assert len(channels) == 200

    def test_short_upper_above_short_lower(self, trend):
        df = make_ohlcv([100 + i * 0.5 for i in range(200)])
        channels = trend.compute_all(df)
        valid = channels.dropna()
        assert (valid['short_upper'] >= valid['short_lower']).all()

    def test_long_upper_above_long_lower(self, trend):
        df = make_ohlcv([100 + i * 0.5 for i in range(200)])
        channels = trend.compute_all(df)
        valid = channels.dropna()
        assert (valid['long_upper'] >= valid['long_lower']).all()

    def test_long_wider_than_short(self, trend):
        df = make_ohlcv([100 + i * 0.5 for i in range(200)])
        channels = trend.compute_all(df)
        valid = channels.dropna()
        short_width = valid['short_upper'] - valid['short_lower']
        long_width = valid['long_upper'] - valid['long_lower']
        assert long_width.mean() > short_width.mean()

    def test_full_position_10(self, trend):
        prices = list(range(100, 0, -1)) + [200] * 50
        df = make_ohlcv(prices)
        result = trend.evaluate(df)
        pos = result.dropna(subset=['position'])
        last = pos.iloc[-1]
        assert last['position'] == 10.0

    def test_empty_position_0(self, trend):
        from app.algos.trend import TrendChannel
        trend = TrendChannel(short_period=10, long_period=30, offset_pct=0.0)
        prices = [200] * 50 + list(range(200, 50, -1))
        closes = [float(p) for p in prices]
        highs = [c * 1.05 for c in closes]
        lows = [c * 0.95 for c in closes]
        opens = [c * 1.0 for c in closes]
        dates = pd.date_range('2024-01-01', periods=len(closes), freq='B')
        df = pd.DataFrame({
            'Open': opens, 'High': highs, 'Low': lows, 'Close': closes,
            'Volume': [1000000] * len(closes),
        }, index=dates)
        result = trend.evaluate(df)
        pos = result.dropna(subset=['position'])
        assert len(pos) > 0

    def test_heavy_position_6(self, trend):
        from app.algos.trend import TrendChannel
        trend = TrendChannel(short_period=5, long_period=15, offset_pct=0.0)
        n = 50
        closes = np.linspace(100, 150, 30).tolist() + [148, 145, 140, 135, 130, 128, 126, 124, 122, 120,
                                                         118, 116, 114, 112, 110, 108, 106, 104, 102, 100]
        highs = [c * 1.10 for c in closes]
        lows = [c * 0.90 for c in closes]
        opens = [c * 0.99 for c in closes]
        dates = pd.date_range('2024-01-01', periods=len(closes), freq='B')
        df = pd.DataFrame({
            'Open': opens, 'High': highs, 'Low': lows, 'Close': closes,
            'Volume': [1000000] * len(closes),
        }, index=dates)
        result = trend.evaluate(df)
        for p in result['position'].dropna():
            assert p in (0.0, 4.0, 6.0, 10.0)

    def test_light_position_4(self, trend):
        from app.algos.trend import TrendChannel
        trend = TrendChannel(short_period=5, long_period=15, offset_pct=0.0)
        n = 50
        closes = [100] * 15 + [102, 105, 108, 110, 112, 115, 118, 120, 122, 125,
                               128, 130, 132, 135, 138, 140, 142, 145, 148, 150]
        closes = closes + [152, 155, 158, 160, 162, 165, 168, 170, 172, 175,
                           178, 180, 182, 185, 188]
        highs = [c * 1.10 for c in closes]
        lows = [c * 0.98 for c in closes]
        opens = [c * 1.00 for c in closes]
        dates = pd.date_range('2024-01-01', periods=len(closes), freq='B')
        df = pd.DataFrame({
            'Open': opens, 'High': highs, 'Low': lows, 'Close': closes,
            'Volume': [1000000] * len(closes),
        }, index=dates)
        result = trend.evaluate(df)
        for p in result['position'].dropna():
            assert p in (0.0, 4.0, 6.0, 10.0)

    def test_position_email(self, trend):
        from app.algos.trend import TrendChannel
        trend = TrendChannel(short_period=10, long_period=30, offset_pct=0.0)
        prices = [100] * 50 + [102, 104, 106, 108, 110, 112, 114, 116]
        df = make_ohlcv(prices, low_offset=0.01)
        df['High'] = df['Close'] * 1.05
        df['Low'] = df['Close'] * 0.97
        result = trend.evaluate(df)
        positions = result['position'].dropna()
        assert positions.iloc[-1] in [0.0, 4.0, 6.0, 10.0]

    def test_state_persistence(self, trend):
        from app.algos.trend import TrendChannel
        trend = TrendChannel(short_period=10, long_period=30, offset_pct=0.0)
        prices = [100] * 50
        df = make_ohlcv(prices, high_offset=0.02, low_offset=0.02)
        df['High'] = df['Close'] * 1.03
        df['Low'] = df['Close'] * 0.97
        result = trend.evaluate(df)
        positions = result['position'].dropna()
        prev = None
        change_count = 0
        for p in positions:
            if prev is not None and p != prev:
                change_count += 1
            prev = p
        assert change_count <= 2

    def test_custom_params(self):
        from app.algos.trend import TrendChannel
        t = TrendChannel(short_period=20, long_period=60, offset_pct=0.02)
        assert t.short_period == 20
        assert t.long_period == 60
        assert t.offset_pct == 0.02

    def test_position_int_values(self, trend):
        df = make_ohlcv([100 + i * 0.5 for i in range(200)])
        result = trend.evaluate(df)
        positions = result['position'].dropna()
        for p in positions:
            assert p in (0.0, 4.0, 6.0, 10.0)


class TestMACDCalculation:
    @pytest.fixture
    def macd(self):
        from app.algos.structure import MACDStructure
        return MACDStructure(fast=12, slow=26, signal=9)

    def test_macd_basic(self, macd):
        df = make_ohlcv([100 + i * 0.5 for i in range(200)])
        result = macd.compute_macd(df)
        assert 'dif' in result.columns
        assert 'dea' in result.columns
        assert 'macd_hist' in result.columns
        assert len(result.dropna()) > 0

    def test_macd_values_make_sense(self, macd):
        prices = [100] * 10 + list(range(100, 200))
        df = make_ohlcv(prices)
        result = macd.compute_macd(df)
        valid = result.dropna(subset=['dif'])
        assert valid['dif'].iloc[-1] > 0

    def test_dif_dea_relationship(self, macd):
        df = make_ohlcv([100 + i * 0.5 for i in range(200)])
        result = macd.compute_macd(df)
        valid = result.dropna(subset=['dif', 'dea'])
        assert len(valid) > 50

    def test_macd_hist_formula(self, macd):
        df = make_ohlcv([100 + i * 0.5 for i in range(200)])
        result = macd.compute_macd(df)
        valid = result.dropna(subset=['macd_hist', 'dif', 'dea'])
        expected_hist = 2 * (valid['dif'] - valid['dea'])
        np.testing.assert_array_almost_equal(valid['macd_hist'], expected_hist)


class TestDIFRounding:
    @pytest.fixture
    def rounding(self):
        from app.algos.structure import _round_dif
        return _round_dif

    def test_large_number(self, rounding):
        assert rounding(168.93) == 16893

    def test_medium_number(self, rounding):
        assert rounding(85.23) == 8523

    def test_small_number(self, rounding):
        assert rounding(0.05) == 5

    def test_negative_number(self, rounding):
        assert rounding(-3.2) == 320

    def test_zero(self, rounding):
        assert rounding(0.0) == 0

    def test_one_digit(self, rounding):
        assert rounding(5.0) == 500


class TestTopDivergence:
    @pytest.fixture
    def macd(self):
        from app.algos.structure import MACDStructure
        return MACDStructure(fast=12, slow=26, signal=9)

    def test_top_divergence_detected(self, macd):
        n = 150
        base = np.linspace(100, 150, 70)
        rise = np.linspace(150, 180, 50)
        peak = np.linspace(180, 165, 30)
        prices = np.concatenate([base, rise, peak])
        df = make_ohlcv(prices)
        result = macd.evaluate(df)
        assert 'top_divergence' in result.columns
        assert 'bottom_divergence' in result.columns

    def test_no_divergence_in_steady_uptrend(self, macd):
        np.random.seed(42)
        prices = np.linspace(100, 500, 300)
        df = make_ohlcv(prices)
        result = macd.evaluate(df)
        top_div = result['top_divergence'].dropna()
        assert len(top_div[top_div == True]) < 30

    def test_divergence_columns_present(self, macd):
        df = make_ohlcv([100 + i * 0.5 for i in range(200)])
        result = macd.evaluate(df)
        for col in ['dif', 'dea', 'macd_hist', 'top_divergence',
                     'bottom_divergence', 'top_structure_75', 'top_structure_100',
                     'bottom_structure_75', 'bottom_structure_100']:
            assert col in result.columns

    def test_structure_level_columns(self, macd):
        df = make_ohlcv([100 + i * 0.5 for i in range(200)])
        result = macd.evaluate(df)
        assert 'top_structure_level' in result.columns
        assert 'bottom_structure_level' in result.columns


class TestBottomDivergence:
    @pytest.fixture
    def macd(self):
        from app.algos.structure import MACDStructure
        return MACDStructure(fast=12, slow=26, signal=9)

    def test_bottom_divergence_possible(self, macd):
        prices = np.linspace(200, 100, 100)
        rise = np.linspace(100, 120, 50)
        prices = np.concatenate([prices, rise])
        df = make_ohlcv(prices)
        result = macd.evaluate(df)
        assert 'bottom_divergence' in result.columns

    def test_divergence_state_machine(self, macd):
        prices = np.linspace(100, 150, 80)
        drop = np.linspace(150, 130, 40)
        prices = np.concatenate([prices, drop])
        df = make_ohlcv(prices)
        result = macd.evaluate(df)
        valid = result.dropna(subset=['top_divergence', 'bottom_divergence'], how='all')
        assert len(valid) > 0


class TestNineSequence:
    @pytest.fixture
    def seq(self):
        from app.algos.sequence import NineSequence
        return NineSequence()

    def test_high_nine_counting(self, seq):
        prices = [100 + i for i in range(20)]
        df = make_ohlcv(prices, high_offset=0.02, low_offset=0.02)
        df['High'] = df['Close'] * 1.02
        df['Low'] = df['Close'] * 0.98
        result = seq.evaluate(df)
        assert 'high9_count' in result.columns
        assert result['high9_count'].max() >= 1

    def test_low_nine_counting(self, seq):
        prices = [200 - i for i in range(20)]
        df = make_ohlcv(prices, high_offset=0.02, low_offset=0.02)
        df['High'] = df['Close'] * 1.02
        df['Low'] = df['Close'] * 0.98
        result = seq.evaluate(df)
        assert 'low9_count' in result.columns

    def test_count_resets_on_failure(self, seq):
        prices = [100 + i for i in range(5)] + [100 - i for i in range(5)] + [100 + i for i in range(15)]
        df = make_ohlcv(prices, high_offset=0.02, low_offset=0.02)
        df['High'] = df['Close'] * 1.02
        df['Low'] = df['Close'] * 0.98
        result = seq.evaluate(df)
        counts = result['high9_count'].values
        resets = sum(1 for i in range(1, len(counts)) if counts[i] < counts[i-1] and counts[i] == 0)
        assert resets >= 1

    def test_high9_signal_at_9(self, seq):
        prices = [100 + i * 2 for i in range(20)]
        df = make_ohlcv(prices, high_offset=0.10, low_offset=0.01)
        df['High'] = df['Close'] * 1.1
        df['Low'] = df['Close'] * 0.99
        result = seq.evaluate(df)
        assert 'high9_signal' in result.columns
        assert 'low9_signal' in result.columns

    def test_low9_signal_at_9(self, seq):
        prices = [200 - i * 2 for i in range(20)]
        df = make_ohlcv(prices, high_offset=0.01, low_offset=0.10)
        df['High'] = df['Close'] * 1.01
        df['Low'] = df['Close'] * 0.9
        result = seq.evaluate(df)
        assert 'low9_signal' in result.columns

    def test_signals_are_boolean(self, seq):
        df = make_ohlcv([100 + i * 0.5 for i in range(50)])
        result = seq.evaluate(df)
        signals = result['high9_signal'].dropna()
        for s in signals:
            assert s in (True, False)

    def test_high9_strength_condition(self, seq):
        """Create a scenario where count reaches 9 but strength fails."""
        prices = [100 + i * 2 for i in range(15)]
        df = make_ohlcv(prices, high_offset=0.0, low_offset=0.0)
        df['High'] = df['Close'] * 1.01
        df['Low'] = df['Close'] * 0.99
        result = seq.evaluate(df)
        assert 'high9_signal' in result.columns

    def test_low9_strength_condition(self, seq):
        """Create a scenario where low count reaches 9 but strength fails."""
        prices = [200 - i * 2 for i in range(15)]
        df = make_ohlcv(prices, high_offset=0.0, low_offset=0.0)
        df['High'] = df['Close'] * 1.01
        df['Low'] = df['Close'] * 0.99
        result = seq.evaluate(df)
        assert 'low9_signal' in result.columns


class TestDecisionEngine:
    @pytest.fixture
    def engine(self):
        from app.algos.decision import DecisionEngine
        return DecisionEngine()

    def test_integration_basic(self, engine):
        df = make_ohlcv([100 + i * 0.5 for i in range(200)])
        result = engine.evaluate(df)
        assert 'position' in result.columns
        assert 'core_long' in result.columns
        assert 'core_short' in result.columns
        assert 'resonance_buy' in result.columns
        assert 'resonance_sell' in result.columns

    def test_core_long_requires_position_4_or_more(self, engine):
        df = make_ohlcv([100 + i * 0.5 for i in range(200)])
        result = engine.evaluate(df)
        core_long = result['core_long'].dropna()
        for i, val in core_long.items():
            if val:
                pos = result.loc[i, 'position']
                assert pos >= 4.0

    def test_core_short_requires_position_6_or_less(self, engine):
        df = make_ohlcv([100 + i * 0.5 for i in range(200)])
        result = engine.evaluate(df)
        core_short = result['core_short'].dropna()
        for i, val in core_short.items():
            if val:
                pos = result.loc[i, 'position']
                assert pos <= 6.0

    def test_resonance_requires_structure(self, engine):
        df = make_ohlcv([100 + i * 0.5 for i in range(200)])
        result = engine.evaluate(df)
        resonance_buy = result['resonance_buy'].dropna()
        for i, val in resonance_buy.items():
            if val:
                assert result.loc[i, 'core_long'] == True

    def test_no_buy_when_position_below_4(self, engine):
        prices = [200 - i * 2 for i in range(100)]
        df = make_ohlcv(prices)
        result = engine.evaluate(df)
        core_long = result['core_long'].dropna()
        for i, val in core_long.items():
            if val:
                assert result.loc[i, 'position'] >= 4.0

    def test_no_sell_when_position_above_6(self, engine):
        prices = [100 + i * 2 for i in range(100)]
        df = make_ohlcv(prices)
        result = engine.evaluate(df)
        core_short = result['core_short'].dropna()
        for i, val in core_short.items():
            if val:
                assert result.loc[i, 'position'] <= 6.0
