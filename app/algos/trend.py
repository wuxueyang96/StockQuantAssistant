import pandas as pd
import numpy as np


class TrendChannel:
    def __init__(self, short_period: int = 26, long_period: int = 90, offset_pct: float = 0.03):
        self.short_period = short_period
        self.long_period = long_period
        self.offset_pct = offset_pct

    def compute_all(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算双通道。algorithm.md §一 规定：
            上轨 = EMA( RollingMax(High, N), N ) × (1 + offset)
            下轨 = EMA( RollingMin(Low,  N), N ) × (1 − offset)
        先滚动取极值再做 EMA，得到"近期高低点中枢"，这才是通道支撑/阻力语义；
        若直接对 High/Low 求 EMA 会退化成普通均线，应避免。
        """
        result = df.copy()

        ns = self.short_period
        nl = self.long_period

        short_rmax = df['High'].rolling(ns, min_periods=1).max()
        short_rmin = df['Low'].rolling(ns, min_periods=1).min()
        long_rmax = df['High'].rolling(nl, min_periods=1).max()
        long_rmin = df['Low'].rolling(nl, min_periods=1).min()

        result['short_upper'] = short_rmax.ewm(span=ns, adjust=False).mean() * (1 + self.offset_pct)
        result['short_lower'] = short_rmin.ewm(span=ns, adjust=False).mean() * (1 - self.offset_pct)
        result['long_upper'] = long_rmax.ewm(span=nl, adjust=False).mean() * (1 + self.offset_pct)
        result['long_lower'] = long_rmin.ewm(span=nl, adjust=False).mean() * (1 - self.offset_pct)

        return result

    def evaluate(self, df: pd.DataFrame) -> pd.DataFrame:
        result = self.compute_all(df)
        positions = []
        prev_position = np.nan

        for i in range(len(result)):
            row = result.iloc[i]
            close = row['Close']
            sh_up = row['short_upper']
            sh_lo = row['short_lower']
            lg_up = row['long_upper']
            lg_lo = row['long_lower']

            if pd.isna(sh_up) or pd.isna(lg_up):
                positions.append(np.nan)
                continue

            if close > sh_up and close > lg_up:
                pos = 10.0
            elif close < sh_lo and close < lg_lo:
                pos = 0.0
            elif close < sh_lo and close > lg_up:
                pos = 6.0
            elif close > sh_up and close < lg_up:
                pos = 4.0
            else:
                pos = prev_position if not pd.isna(prev_position) else np.nan

            positions.append(pos)
            prev_position = pos

        result['position'] = positions
        return result

    def next_day_thresholds(self, df: pd.DataFrame) -> dict:
        """返回下一交易日的趋势量化标准（趋势线阈值），即收盘价需要突破的点位。

        趋势只看日线收盘价。阈值就是双通道的上轨/下轨数值。
        下一交易日的阈值 = 今日通道值（EMA 对新数据不敏感，可外推）。
        """
        result = self.compute_all(df)
        last = result.iloc[-1]

        thresholds = {
            'short_upper': round(float(last['short_upper']), 4) if pd.notna(last.get('short_upper')) else None,
            'short_lower': round(float(last['short_lower']), 4) if pd.notna(last.get('short_lower')) else None,
            'long_upper': round(float(last['long_upper']), 4) if pd.notna(last.get('long_upper')) else None,
            'long_lower': round(float(last['long_lower']), 4) if pd.notna(last.get('long_lower')) else None,
        }
        return thresholds
