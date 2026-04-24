import pandas as pd
import numpy as np


def _round_dif(value: float) -> int:
    """DIF 数值取整（乘 100 取整，保持比较单调性）"""
    return int(abs(value) * 100)


class MACDStructure:
    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9, lookback: int = 50):
        self.fast = fast
        self.slow = slow
        self.signal = signal
        self.lookback = lookback

    def compute_macd(self, df: pd.DataFrame) -> pd.DataFrame:
        result = df.copy()
        ema_fast = df['Close'].ewm(span=self.fast, adjust=False).mean()
        ema_slow = df['Close'].ewm(span=self.slow, adjust=False).mean()
        result['dif'] = ema_fast - ema_slow
        result['dea'] = result['dif'].ewm(span=self.signal, adjust=False).mean()
        result['macd_hist'] = 2 * (result['dif'] - result['dea'])
        return result

    def evaluate(self, df: pd.DataFrame) -> pd.DataFrame:
        result = self.compute_macd(df)
        n = len(result)

        result['top_divergence'] = False
        result['bottom_divergence'] = False
        result['top_structure_75'] = False
        result['top_structure_100'] = False
        result['bottom_structure_75'] = False
        result['bottom_structure_100'] = False
        result['top_structure_level'] = 0.0
        result['bottom_structure_level'] = 0.0

        min_bars = max(self.slow + self.signal + 10, self.lookback)
        if n < min_bars:
            return result

        top_state = 'normal'
        bottom_state = 'normal'
        top_div_start = None
        bottom_div_start = None
        top_price_peak = -np.inf
        top_dif_peak = -np.inf
        bottom_price_valley = np.inf
        bottom_dif_valley = np.inf
        top_dif_peak_idx = 0
        bottom_dif_valley_idx = 0

        for i in range(min_bars, n):
            price_high = result['High'].iloc[i]
            price_low = result['Low'].iloc[i]
            dif = result['dif'].iloc[i]
            dea = result['dea'].iloc[i]

            if pd.isna(dif) or pd.isna(dea):
                continue

            rounded_dif = _round_dif(dif)

            # --- top divergence logic ---
            if price_high > top_price_peak:
                rounded_peak = _round_dif(top_dif_peak) if not np.isinf(top_dif_peak) else -1
                if rounded_dif >= rounded_peak:
                    if top_state in ('top_divergence', 'top_75'):
                        top_state = 'normal'
                    top_price_peak = price_high
                    top_dif_peak = dif
                    top_dif_peak_idx = i
                else:
                    if top_state == 'normal':
                        top_state = 'top_divergence'
                        top_div_start = i
                    top_price_peak = price_high
                    result.at[result.index[i], 'top_divergence'] = True

            elif top_state == 'top_divergence':
                result.at[result.index[i], 'top_divergence'] = True
                prev_dif = result['dif'].iloc[max(0, i - 1)]
                if not pd.isna(prev_dif) and dif < prev_dif and i > top_dif_peak_idx:
                    top_state = 'top_75'
                    result.at[result.index[i], 'top_structure_75'] = True

            elif top_state == 'top_75':
                prev_dif = result['dif'].iloc[max(0, i - 1)]
                prev_dea = result['dea'].iloc[max(0, i - 1)]
                if not pd.isna(prev_dif) and not pd.isna(prev_dea):
                    if dif < dea and prev_dif >= prev_dea:
                        top_state = 'top_100'
                        result.at[result.index[i], 'top_structure_100'] = True
                        if top_div_start is not None:
                            result.at[result.index[i], 'top_structure_level'] = float(i - top_div_start)

            # --- bottom divergence logic ---
            if price_low < bottom_price_valley:
                rounded_valley = _round_dif(bottom_dif_valley) if not np.isinf(bottom_dif_valley) else 999999
                if rounded_dif < rounded_valley:
                    if bottom_state in ('bottom_divergence', 'bottom_75'):
                        bottom_state = 'normal'
                    bottom_price_valley = price_low
                    bottom_dif_valley = dif
                    bottom_dif_valley_idx = i
                else:
                    if bottom_state == 'normal':
                        bottom_state = 'bottom_divergence'
                        bottom_div_start = i
                    bottom_price_valley = price_low
                    result.at[result.index[i], 'bottom_divergence'] = True

            elif bottom_state == 'bottom_divergence':
                result.at[result.index[i], 'bottom_divergence'] = True
                prev_dif = result['dif'].iloc[max(0, i - 1)]
                if not pd.isna(prev_dif) and dif > prev_dif and i > bottom_dif_valley_idx:
                    bottom_state = 'bottom_75'
                    result.at[result.index[i], 'bottom_structure_75'] = True

            elif bottom_state == 'bottom_75':
                prev_dif = result['dif'].iloc[max(0, i - 1)]
                prev_dea = result['dea'].iloc[max(0, i - 1)]
                if not pd.isna(prev_dif) and not pd.isna(prev_dea):
                    if dif > dea and prev_dif <= prev_dea:
                        bottom_state = 'bottom_100'
                        result.at[result.index[i], 'bottom_structure_100'] = True
                        if bottom_div_start is not None:
                            result.at[result.index[i], 'bottom_structure_level'] = float(i - bottom_div_start)

        return result
