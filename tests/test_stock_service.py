import pytest
from app.services.stock_service import (
    detect_market, resolve_stock_name, format_stock_code,
    get_workflow_id, get_table_name, get_yfinance_ticker, is_trading_time,
)


class TestDetectMarket:
    def test_a_stock_with_sz_suffix(self):
        assert detect_market('000001.SZ') == [('a', '000001')]

    def test_a_stock_with_ss_suffix(self):
        assert detect_market('600519.SS') == [('a', '600519')]

    def test_hk_stock_with_hk_suffix(self):
        assert detect_market('00700.HK') == [('hk', '00700')]

    def test_hk_stock_with_hk_suffix_4digit(self):
        assert detect_market('0005.HK') == [('hk', '00005')]

    def test_us_stock_with_us_suffix(self):
        assert detect_market('AAPL.US') == [('us', 'AAPL')]

    def test_a_stock_6digit_code(self):
        assert detect_market('000001') == [('a', '000001')]

    def test_a_stock_shanghai_6digit(self):
        assert detect_market('600519') == [('a', '600519')]

    def test_hk_stock_5digit_code(self):
        assert detect_market('00700') == [('hk', '00700')]

    def test_us_stock_pure_letters(self):
        assert detect_market('AAPL') == [('us', 'AAPL')]

    def test_case_insensitive(self):
        assert detect_market('aapl') == [('us', 'AAPL')]

    def test_invalid_code_raises(self):
        with pytest.raises(ValueError):
            detect_market('ABC.XX')

    def test_unknown_name_not_in_db(self, app):
        with pytest.raises(ValueError, match='stock_codes'):
            detect_market('不存在的股票')


class TestResolveStockName:
    def test_resolve_multi_market(self, app, seed_stock_codes):
        result = resolve_stock_name('阿里巴巴')
        assert len(result) == 2
        assert ('hk', '09988') in result
        assert ('us', 'BABA') in result

    def test_resolve_single_market(self, app, seed_stock_codes):
        result = resolve_stock_name('贵州茅台')
        assert result == [('a', '600519')]

    def test_resolve_hk_only(self, app, seed_stock_codes):
        result = resolve_stock_name('小米')
        assert result == [('hk', '01810')]

    def test_resolve_us_only(self, app, seed_stock_codes):
        result = resolve_stock_name('苹果')
        assert result == [('us', 'AAPL')]

    def test_resolve_unknown_name(self, app):
        with pytest.raises(ValueError, match='stock_codes'):
            resolve_stock_name('完全不存在的股票名')


class TestFormatStockCode:
    def test_a_stock_shanghai(self):
        assert format_stock_code('a', '600519') == '600519.SS'

    def test_a_stock_shenzhen(self):
        assert format_stock_code('a', '000001') == '000001.SZ'

    def test_hk_stock(self):
        assert format_stock_code('hk', '00700') == '00700.HK'

    def test_us_stock(self):
        assert format_stock_code('us', 'AAPL') == 'AAPL.US'


class TestGetWorkflowId:
    def test_a_stock_daily(self):
        assert get_workflow_id('a', '000001', 'daily') == 'A_000001.SZ_daily'

    def test_hk_stock_120min(self):
        assert get_workflow_id('hk', '00700', '120min') == 'HK_00700.HK_120min'

    def test_us_stock_60min(self):
        assert get_workflow_id('us', 'AAPL', '60min') == 'US_AAPL.US_60min'

    def test_table_name_matches_workflow_id(self):
        for interval in ['daily', '120min', '90min', '60min']:
            wf_id = get_workflow_id('a', '000001', interval)
            tbl = get_table_name('a', '000001', interval)
            assert tbl == wf_id


class TestGetYfinanceTicker:
    def test_a_stock_shanghai(self):
        assert get_yfinance_ticker('a', '600519') == '600519.SS'

    def test_a_stock_shenzhen(self):
        assert get_yfinance_ticker('a', '000001') == '000001.SZ'

    def test_hk_stock(self):
        assert get_yfinance_ticker('hk', '00700') == '0700.HK'

    def test_us_stock(self):
        assert get_yfinance_ticker('us', 'AAPL') == 'AAPL'


class TestIsTradingTime:
    def test_returns_bool(self):
        assert isinstance(is_trading_time('a'), bool)

    def test_unknown_market(self):
        assert is_trading_time('jp') is False


class TestDetectMarketMultiMarket:
    def test_detect_name_multi_market(self, app, seed_stock_codes):
        results = detect_market('阿里巴巴')
        assert len(results) == 2

    def test_detect_name_single_market(self, app, seed_stock_codes):
        results = detect_market('贵州茅台')
        assert len(results) == 1
