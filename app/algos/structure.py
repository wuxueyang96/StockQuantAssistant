"""MACD 结构量化（参见 docs/algorithm.md §二 / docs/design.md §3.5）。

状态机（顶部，底部对称）：
    normal
      └─ [价格创窗口新高 + DIF 未创窗口新高] ─▶ top_divergence
            │      （peak_dif 每根 K 线都尝试更新，保留正负号）
            │      [价格再创新高 且 DIF 也再创新高] ─▶ 钝化破坏 → normal
            │
            └─ [DIF 连续 K 根下行 且 DIF < peak_dif] ─▶ top_75
                  │
                  └─ [上一根 DIF ≥ DEA 且 当根 DIF < DEA] ─▶ top_100
                        │
                        └─ 100% 触发当根记录后立即 reset → normal
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np
import pandas as pd


def strictly_greater(a: float, b: float, eps: float = 0.001) -> bool:
    """带符号的相对阈值比较：a 严格大于 b。

    `(a - b) > eps × max(|a|, |b|, 1e-6)`。对负数与小数 DIF 都安全，弃用原
    "数量级前两位取整"规则（该规则对负值与 |DIF|<1 存在语义反转和除零问题）。

    `eps` 是过滤浮点/数值扰动用的相对容差，默认 0.001（0.1%）。算法文档把
    它写成 2% 的上限语义，但实际只用作"避免假相等"，过大会让稳定上涨场景下
    合理增长被误判为钝化，因此默认取小值。
    """
    if a is None or b is None:
        return False
    try:
        if math.isnan(a) or math.isnan(b):
            return False
    except (TypeError, ValueError):
        return False
    return (a - b) > eps * max(abs(a), abs(b), 1e-6)


def _magnitude_prefix(value: float, scale: int = None) -> int:
    """已弃用：保留以维持兼容性。仅供旧测试与可视化使用，状态机不再依赖。

    取数值数量级的前两位数字，例如 168.93 → digits=3, scale=1 → 16。
    """
    if value == 0 or np.isnan(value) or np.isinf(value):
        return 0
    abs_val = abs(value)
    if scale is None:
        digits = len(str(int(abs_val)))
        scale = max(0, digits - 2)
    return int(abs_val / 10 ** scale)


class MACDStructure:
    def __init__(
        self,
        fast: int = 12,
        slow: int = 26,
        signal: int = 9,
        lookback: int = 50,
        smooth_k: int = 2,
        eps: float = 0.001,
        effective_horizon: int = 5,
    ):
        self.fast = fast
        self.slow = slow
        self.signal = signal
        self.lookback = lookback
        self.smooth_k = smooth_k
        self.eps = eps
        self.effective_horizon = effective_horizon
        self.alpha_fast = 2.0 / (fast + 1)
        self.alpha_slow = 2.0 / (slow + 1)
        self.alpha_diff = self.alpha_fast - self.alpha_slow

    # ------------------------------------------------------------------ MACD
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

    # ------------------------------------------------------------------ helpers
    def _greater(self, a: float, b: float) -> bool:
        return strictly_greater(a, b, eps=self.eps)

    def _less(self, a: float, b: float) -> bool:
        """a 严格小于 b（带符号相对阈值）。"""
        return strictly_greater(b, a, eps=self.eps)

    # ------------------------------------------------------------------ main
    def evaluate(self, df: pd.DataFrame) -> pd.DataFrame:
        result = self.compute_macd(df)
        n = len(result)

        # 初始化输出列
        for col in (
            'top_divergence', 'bottom_divergence',
            'top_structure_75', 'top_structure_100',
            'bottom_structure_75', 'bottom_structure_100',
            'top_structure_active', 'bottom_structure_active',
        ):
            result[col] = False
        result['top_structure_level'] = 0.0
        result['bottom_structure_level'] = 0.0
        result['structure_effective_until'] = pd.NaT

        # 数据不够直接返回
        min_bars = max(self.slow + self.signal + 2, 2)
        if n < min_bars:
            return result

        H = result['High'].values
        L = result['Low'].values
        DIF = result['dif'].values
        DEA = result['dea'].values

        # ------------------------------------------------ 顶部状态机
        top_state = 'normal'
        top_peak_price: Optional[float] = None
        top_peak_dif: Optional[float] = None
        top_div_start: Optional[int] = None
        top_decline_run = 0
        top_active_until = -1  # 截止 K 线 idx（含）

        # ------------------------------------------------ 底部状态机
        bot_state = 'normal'
        bot_valley_price: Optional[float] = None
        bot_valley_dif: Optional[float] = None
        bot_div_start: Optional[int] = None
        bot_rise_run = 0
        bot_active_until = -1

        eff_until_idx = [None] * n  # 记录每根 K 线在该时刻的有效期截止 idx

        for i in range(n):
            d = DIF[i]; a = DEA[i]; h = H[i]; l = L[i]
            if pd.isna(d) or pd.isna(a):
                # 仍要更新 active 列
                if i <= top_active_until:
                    result.at[result.index[i], 'top_structure_active'] = True
                if i <= bot_active_until:
                    result.at[result.index[i], 'bottom_structure_active'] = True
                continue
            prev_d = DIF[i - 1] if i > 0 else float('nan')
            prev_a = DEA[i - 1] if i > 0 else float('nan')

            # ---------------- 顶部逻辑 ----------------
            top_event = self._step_top(
                i, h, d, a, prev_d, prev_a, result,
                top_state, top_peak_price, top_peak_dif, top_div_start, top_decline_run,
            )
            (top_state, top_peak_price, top_peak_dif, top_div_start,
             top_decline_run, top_fired_at) = top_event
            if top_fired_at is not None:
                top_active_until = max(top_active_until, i + self.effective_horizon)

            # ---------------- 底部逻辑 ----------------
            bot_event = self._step_bottom(
                i, l, d, a, prev_d, prev_a, result,
                bot_state, bot_valley_price, bot_valley_dif, bot_div_start, bot_rise_run,
            )
            (bot_state, bot_valley_price, bot_valley_dif, bot_div_start,
             bot_rise_run, bot_fired_at) = bot_event
            if bot_fired_at is not None:
                bot_active_until = max(bot_active_until, i + self.effective_horizon)

            # ---------------- active 与有效期 ----------------
            if i <= top_active_until:
                result.at[result.index[i], 'top_structure_active'] = True
            if i <= bot_active_until:
                result.at[result.index[i], 'bottom_structure_active'] = True

            # 记录任一方向最远的有效期截止
            far_until = max(top_active_until, bot_active_until)
            if far_until >= i:
                eff_until_idx[i] = min(far_until, n - 1)

        # 把 effective_until 用时间戳填充
        idx = result.index
        eff_until_series = []
        for j in eff_until_idx:
            if j is None:
                eff_until_series.append(pd.NaT)
            else:
                eff_until_series.append(idx[j])
        result['structure_effective_until'] = eff_until_series

        return result

    # ------------------------------------------------------------------ top step
    def _step_top(self, i, h, d, a, prev_d, prev_a, result,
                  state, peak_price, peak_dif, div_start, decline_run):
        fired_at = None
        if state == 'normal':
            # 累积窗口：normal 期间也跟踪 peak_price / peak_dif
            if peak_price is None or h > peak_price:
                # price 创新高
                if peak_dif is None or self._greater(d, peak_dif):
                    # DIF 也创新高 → 同步更新极值，保持 normal
                    peak_price = h
                    peak_dif = d
                else:
                    # DIF 没创新高 → 进入钝化
                    state = 'top_divergence'
                    div_start = i
                    peak_price = h
                    decline_run = 0
                    result.at[result.index[i], 'top_divergence'] = True
            else:
                # price 没创新高，但要尝试更新 peak_dif（每根 K 线）
                if peak_dif is None or self._greater(d, peak_dif):
                    peak_dif = d

        elif state in ('top_divergence', 'top_75'):
            # 钝化窗口内：每根 K 线都尝试更新 peak_dif
            if peak_dif is None:
                peak_dif = d

            if h > peak_price:
                # price 创窗口新高
                if self._greater(d, peak_dif):
                    # DIF 也创新高 → 钝化破坏，回 normal
                    state = 'normal'
                    peak_price = h
                    peak_dif = d
                    div_start = None
                    decline_run = 0
                    return state, peak_price, peak_dif, div_start, decline_run, fired_at
                else:
                    # DIF 没创新高，钝化"事件"在这一根 K 线触发
                    peak_price = h
                    if state == 'top_divergence':
                        result.at[result.index[i], 'top_divergence'] = True
            else:
                # price 没创新高，仅尝试更新 peak_dif（不视为破坏）
                if self._greater(d, peak_dif):
                    peak_dif = d

            # ---- 判定 100%（优先级最高，可同根叠加 75%） ----
            if not pd.isna(prev_d) and not pd.isna(prev_a):
                if prev_d >= prev_a and d < a:
                    # DIF 由上而下穿过 DEA → 顶部 100% 完成
                    result.at[result.index[i], 'top_structure_100'] = True
                    # 若 75% 还没触发，则同根一并标记（顶部确认事件本身已含动能转向）
                    if state == 'top_divergence':
                        result.at[result.index[i], 'top_structure_75'] = True
                    if div_start is not None:
                        result.at[result.index[i], 'top_structure_level'] = float(i - div_start)
                    fired_at = i
                    # reset 回 normal，开始下一轮跟踪
                    state = 'normal'
                    peak_price = h
                    peak_dif = d
                    div_start = None
                    decline_run = 0
                    return state, peak_price, peak_dif, div_start, decline_run, fired_at

            # ---- 判定 75% ----
            if state == 'top_divergence':
                if not pd.isna(prev_d) and d < prev_d:
                    decline_run += 1
                else:
                    decline_run = 0
                if decline_run >= self.smooth_k and self._less(d, peak_dif):
                    state = 'top_75'
                    result.at[result.index[i], 'top_structure_75'] = True
                    fired_at = i

        return state, peak_price, peak_dif, div_start, decline_run, fired_at

    # ------------------------------------------------------------------ bottom step
    def _step_bottom(self, i, l, d, a, prev_d, prev_a, result,
                     state, valley_price, valley_dif, div_start, rise_run):
        fired_at = None
        if state == 'normal':
            if valley_price is None or l < valley_price:
                # price 创新低
                if valley_dif is None or self._less(d, valley_dif):
                    # DIF 也创新低 → 同步更新极值
                    valley_price = l
                    valley_dif = d
                else:
                    # DIF 没创新低 → 进入底部钝化
                    state = 'bottom_divergence'
                    div_start = i
                    valley_price = l
                    rise_run = 0
                    result.at[result.index[i], 'bottom_divergence'] = True
            else:
                # price 没创新低，仍要尝试更新 valley_dif（变得更负）
                if valley_dif is None or self._less(d, valley_dif):
                    valley_dif = d

        elif state in ('bottom_divergence', 'bottom_75'):
            if valley_dif is None:
                valley_dif = d

            if l < valley_price:
                # price 创窗口新低
                if self._less(d, valley_dif):
                    # DIF 也创新低 → 钝化破坏
                    state = 'normal'
                    valley_price = l
                    valley_dif = d
                    div_start = None
                    rise_run = 0
                    return state, valley_price, valley_dif, div_start, rise_run, fired_at
                else:
                    # DIF 没创新低 → 钝化"事件"在这一根 K 线触发
                    valley_price = l
                    if state == 'bottom_divergence':
                        result.at[result.index[i], 'bottom_divergence'] = True
            else:
                if self._less(d, valley_dif):
                    valley_dif = d

            # ---- 判定 100%（优先级最高，可同根叠加 75%） ----
            if not pd.isna(prev_d) and not pd.isna(prev_a):
                if prev_d <= prev_a and d > a:
                    result.at[result.index[i], 'bottom_structure_100'] = True
                    if state == 'bottom_divergence':
                        result.at[result.index[i], 'bottom_structure_75'] = True
                    if div_start is not None:
                        result.at[result.index[i], 'bottom_structure_level'] = float(i - div_start)
                    fired_at = i
                    state = 'normal'
                    valley_price = l
                    valley_dif = d
                    div_start = None
                    rise_run = 0
                    return state, valley_price, valley_dif, div_start, rise_run, fired_at

            # ---- 判定 75% ----
            if state == 'bottom_divergence':
                if not pd.isna(prev_d) and d > prev_d:
                    rise_run += 1
                else:
                    rise_run = 0
                if rise_run >= self.smooth_k and self._greater(d, valley_dif):
                    state = 'bottom_75'
                    result.at[result.index[i], 'bottom_structure_75'] = True
                    fired_at = i

        return state, valley_price, valley_dif, div_start, rise_run, fired_at

    # ------------------------------------------------------------------ thresholds
    def next_period_thresholds(self, df: pd.DataFrame) -> dict:
        """返回下一周期结构量化标准（触发各类结构信号的收盘价阈值）。

        基于 DIF = A + B × C 的线性关系反推：
            A = EMA_fast_cur × (1 - αf) - EMA_slow_cur × (1 - αs)
            B = αf - αs（正）
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
            result['macd_dif_cross_dea_price'] = round(float((dea_cur - A) / B), 4)

        dif_cur = last['dif']
        if pd.notna(dif_cur):
            result['macd_dif_turn_price'] = round(float((dif_cur - A) / B), 4)

        return result
