import pandas as pd
import numpy as np


def _magnitude_prefix(value: float, scale: int = None) -> int:
    """取数值数量级的前两位数字用于比较。

    例如：168.93 → digits=3, scale=1 → prefix=16
         85.23  → digits=2, scale=1 → prefix=8 (统一除数)
    scale 由传入的参考值决定，None 时根据自身位数计算。
    """
    if value == 0 or np.isnan(value) or np.isinf(value):
        return 0
    abs_val = abs(value)
    if scale is None:
        digits = len(str(int(abs_val)))
        scale = max(0, digits - 2)
    return int(abs_val / 10**scale)


class MACDStructure:
    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9, lookback: int = 50):
        self.fast = fast
        self.slow = slow
        self.signal = signal
        self.lookback = lookback
        self.alpha_fast = 2.0 / (fast + 1)
        self.alpha_slow = 2.0 / (slow + 1)
        self.alpha_diff = self.alpha_fast - self.alpha_slow

    def compute_macd(self, df: pd.DataFrame) -> pd.DataFrame:
        result = df.copy()
        ema_fast = df['Close'].ewm(span=self.fast, adjust=False).mean()
        ema_slow = df['Close'].ewm(span=self.slow, adjust=False).mean()
        result['dif'] = ema_fast - ema_slow
        result['dea'] = result['dif'].ewm(span=self.signal, adjust=False).mean()
        result['macd_hist'] = 2 * (result['dif'] - result['dea'])
        result['_ema_fast'] = ema_fast
        result['_ema_slow'] = ema_slow
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

            # --- top divergence logic ---
            if price_high > top_price_peak:
                if not np.isinf(top_dif_peak):
                    scale = max(0, len(str(int(abs(top_dif_peak)))) - 2)
                    cur_prefix = _magnitude_prefix(dif, scale)
                    prev_prefix = _magnitude_prefix(top_dif_peak, scale)
                    if cur_prefix >= prev_prefix:
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
                else:
                    top_price_peak = price_high
                    top_dif_peak = dif
                    top_dif_peak_idx = i

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
                if not np.isinf(bottom_dif_valley):
                    scale = max(0, len(str(int(abs(bottom_dif_valley)))) - 2)
                    cur_prefix = _magnitude_prefix(dif, scale)
                    prev_prefix = _magnitude_prefix(bottom_dif_valley, scale)
                    if cur_prefix <= prev_prefix:
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
                else:
                    bottom_price_valley = price_low
                    bottom_dif_valley = dif
                    bottom_dif_valley_idx = i

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

    def next_period_thresholds(self, df: pd.DataFrame) -> dict:
        """返回下一周期的结构量化标准 — 即下一根 K 线的收盘价触发各类结构信号的阈值。

        基于 DIF = A + B * C 的线性关系反推：
            A = EMA_fast_cur * (1 - αf) - EMA_slow_cur * (1 - αs)
            B = αf - αs  (正数，因为快线 α 更大)
            C_next = (DIF_target - A) / B
        """
        computed = self.compute_macd(df)
        last = computed.iloc[-1]
        result = {
            'dif': round(float(last['dif']), 4) if pd.notna(last.get('dif')) else None,
            'dea': round(float(last['dea']), 4) if pd.notna(last.get('dea')) else None,
        }

        ema_fast = last.get('_ema_fast')
        ema_slow = last.get('_ema_slow')
        if pd.isna(ema_fast) or pd.isna(ema_slow):
            return result

        A = ema_fast * (1 - self.alpha_fast) - ema_slow * (1 - self.alpha_slow)
        B = self.alpha_diff
        if abs(B) < 1e-10:
            return result

        dea_cur = last['dea']
        if pd.notna(dea_cur):
            cross_price = (dea_cur - A) / B
            result['macd_dif_cross_dea_price'] = round(float(cross_price), 4)

        dif_cur = last['dif']
        if pd.notna(dif_cur):
            turn_up_price = (dif_cur - A) / B
            result['macd_dif_turn_price'] = round(float(turn_up_price), 4)

        return result
