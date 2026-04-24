import pandas as pd
import numpy as np


class TrendChannel:
    def __init__(self, short_period: int = 25, long_period: int = 90, offset_pct: float = 0.03):
        self.short_period = short_period
        self.long_period = long_period
        self.offset_pct = offset_pct

    def compute_all(self, df: pd.DataFrame) -> pd.DataFrame:
        result = df.copy()

        short_max_high = df['High'].rolling(self.short_period).max()
        short_min_low = df['Low'].rolling(self.short_period).min()
        long_max_high = df['High'].rolling(self.long_period).max()
        long_min_low = df['Low'].rolling(self.long_period).min()

        result['short_upper'] = short_max_high.ewm(span=self.short_period, adjust=False).mean() * (1 + self.offset_pct)
        result['short_lower'] = short_min_low.ewm(span=self.short_period, adjust=False).mean() * (1 - self.offset_pct)
        result['long_upper'] = long_max_high.ewm(span=self.long_period, adjust=False).mean() * (1 + self.offset_pct)
        result['long_lower'] = long_min_low.ewm(span=self.long_period, adjust=False).mean() * (1 - self.offset_pct)

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
