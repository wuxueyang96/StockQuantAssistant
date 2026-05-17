"""决策引擎（参见 docs/algorithm.md §四 / docs/design.md §3.5 / docs/api.md）。

三级优先级：
- **第一级 趋势**：仓位跃迁 `delta = position − prev_position` → action / weight。
- **第二级 结构**：在 position_T ≥ 6（做多）或 ≤ 4（做空）且结构有效时叠加倍率，
  把 confidence 升级为 `core`。
- **第三级 序列**：与结构同向时再叠 1.2× 倍率，confidence 升级为 `resonance`。

`evaluate(df)` 返回扩展 DataFrame（含内部布尔列），`summary(df)` 把最新 K 线打包为
API 字典（`decision / signals / standards`）。
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from app.algos.trend import TrendChannel
from app.algos.structure import MACDStructure
from app.algos.sequence import NineSequence


POSITION_LABEL = {10.0: '满仓', 6.0: '重仓', 4.0: '轻仓', 0.0: '空仓'}

# 多周期整合：结构仅看 60/90/120 分钟（与日线趋势解耦）
STRUCTURE_INTERVAL_ORDER = ('60min', '90min', '120min')
_STRUCTURE_ENUM_SCORE = {'top_100': 6, 'bottom_100': 6, 'top_75': 4, 'bottom_75': 4, 'none': 0}


def _structure_enum_from_row(row: pd.Series) -> str:
    if bool(row.get('top_structure_100')):
        return 'top_100'
    if bool(row.get('top_structure_75')):
        return 'top_75'
    if bool(row.get('bottom_structure_100')):
        return 'bottom_100'
    if bool(row.get('bottom_structure_75')):
        return 'bottom_75'
    return 'none'


class DecisionEngine:
    def __init__(self, trend=None, structure=None, sequence=None):
        self.trend = trend or TrendChannel()
        self.structure = structure or MACDStructure()
        self.sequence = sequence or NineSequence()

    # ------------------------------------------------------------------ evaluate
    def evaluate(self, df: pd.DataFrame) -> pd.DataFrame:
        trend_r = self.trend.evaluate(df)
        struct_r = self.structure.evaluate(df)
        seq_r = self.sequence.evaluate(df)

        result = df.copy()

        # 趋势
        result['position'] = trend_r['position']
        result['prev_position'] = trend_r['position'].shift(1)

        # 结构（保留内部布尔列；外层 API 折叠为枚举）
        for col in ('top_structure_75', 'top_structure_100',
                    'bottom_structure_75', 'bottom_structure_100',
                    'top_structure_active', 'bottom_structure_active',
                    'structure_effective_until'):
            result[col] = struct_r[col]

        # 序列
        for col in ('high9_signal', 'low9_signal',
                    'high9_active', 'low9_active',
                    'sequence_effective_until'):
            result[col] = seq_r[col]

        n = len(result)

        # 预分配
        result['action'] = 'HOLD'
        result['weight'] = 0.0
        result['confidence'] = 'trend'
        result['position_label'] = ''
        result['core_long'] = False
        result['core_short'] = False
        result['resonance_buy'] = False
        result['resonance_sell'] = False
        result['resonance_level'] = 1.0
        result['resonance_periods'] = [list() for _ in range(n)]
        result['probe'] = False

        # execute_at：下一根 K 线的索引时间；最后一根没有下一根 → NaT
        exec_at = list(result.index[1:]) + [pd.NaT]
        result['execute_at'] = exec_at

        # 主循环
        for i in range(n):
            pos = result['position'].iloc[i]
            prev = result['prev_position'].iloc[i]

            # position_label
            if pd.notna(pos):
                result.at[result.index[i], 'position_label'] = POSITION_LABEL.get(float(pos), '冷启动')
            else:
                result.at[result.index[i], 'position_label'] = '冷启动'

            # 主 BS：仓位跃迁
            if pd.isna(pos) or pd.isna(prev):
                continue

            delta = float(pos) - float(prev)
            if delta > 0:
                action = 'BUY'
                base_weight = delta / 10.0
            elif delta < 0:
                action = 'SELL'
                base_weight = -delta / 10.0
            else:
                action = 'HOLD'
                base_weight = 0.0

            # 结构修边
            bot_active = bool(result['bottom_structure_active'].iloc[i])
            top_active = bool(result['top_structure_active'].iloc[i])
            bot_75 = bool(result['bottom_structure_75'].iloc[i])
            bot_100 = bool(result['bottom_structure_100'].iloc[i])
            top_75 = bool(result['top_structure_75'].iloc[i])
            top_100 = bool(result['top_structure_100'].iloc[i])

            # core_long：position ≥ 6 且 底部结构 active
            core_long = (pos >= 6.0) and bot_active
            # core_short：position ≤ 4 且 顶部结构 active
            core_short = (pos <= 4.0) and top_active
            result.at[result.index[i], 'core_long'] = core_long
            result.at[result.index[i], 'core_short'] = core_short

            confidence = 'trend'
            weight = base_weight

            # 仅在与跃迁方向一致时才叠加倍率
            if action == 'BUY' and core_long:
                mult = 1.5 if bot_100 else 1.2 if bot_75 else 1.2
                weight *= mult
                confidence = 'core'
                if bool(result['low9_active'].iloc[i]):
                    weight *= 1.2
                    confidence = 'resonance'
                    result.at[result.index[i], 'resonance_buy'] = True

            elif action == 'SELL' and core_short:
                mult = 1.5 if top_100 else 1.2 if top_75 else 1.2
                weight *= mult
                confidence = 'core'
                if bool(result['high9_active'].iloc[i]):
                    weight *= 1.2
                    confidence = 'resonance'
                    result.at[result.index[i], 'resonance_sell'] = True

            result.at[result.index[i], 'action'] = action
            result.at[result.index[i], 'weight'] = round(weight, 6)
            result.at[result.index[i], 'confidence'] = confidence

            # 单周期共振信息：当前周期结构 active 时，periods 含当前 interval（由上层填）
            if bot_active or top_active:
                # resonance_periods 留给上层（analysis_service）填具体 interval 列表
                # 这里先放占位，方便上层判断当前周期是否参与共振
                pass

        return result

    # ------------------------------------------------------------------ view (人话翻译层)
    _POSITION_TO_TREND_LABEL = {
        10.0: '上升',
        6.0: '横盘',
        4.0: '横盘',
        0.0: '下降',
    }

    def _extrapolate_next(self, series: pd.Series, window: int = 5):
        """用最近 N 根 K 线均匀斜率外推下一根。返回 float 或 None。"""
        s = series.dropna()
        if len(s) < 2:
            return None
        n = min(window, len(s))
        recent = s.iloc[-n:]
        if len(recent) < 2:
            return float(recent.iloc[-1])
        slope = (recent.iloc[-1] - recent.iloc[0]) / (len(recent) - 1)
        return round(float(recent.iloc[-1] + slope), 4)

    def _make_view(self, decision_df: pd.DataFrame,
                   summary_dict: dict,
                   structure_df: pd.DataFrame,
                   sequence_df: pd.DataFrame) -> dict:
        last = decision_df.iloc[-1]
        pos = summary_dict.get('position', {}).get('current')
        position_label = summary_dict.get('position', {}).get('label')
        close = summary_dict.get('close')

        trend_std = summary_dict.get('standards', {}).get('trend', {}) or {}
        struct_std = summary_dict.get('standards', {}).get('structure', {}) or {}

        # 趋势标签
        trend_label = self._POSITION_TO_TREND_LABEL.get(float(pos), '冷启动') \
            if pos is not None else '冷启动'

        # 明日通道外推
        tomorrow_up = self._extrapolate_next(decision_df.get('position', pd.Series()).index.to_series()) \
            if False else None  # placeholder for IDE
        tomorrow_up = self._extrapolate_next(self.trend.compute_all(decision_df)['short_upper'])
        tomorrow_dn = self._extrapolate_next(self.trend.compute_all(decision_df)['short_lower'])

        # 九转进度（最新一根的 *_count）
        h9_count = int(sequence_df['high9_count'].iloc[-1]) if 'high9_count' in sequence_df.columns else 0
        l9_count = int(sequence_df['low9_count'].iloc[-1]) if 'low9_count' in sequence_df.columns else 0
        h9_count = max(0, min(9, h9_count))
        l9_count = max(0, min(9, l9_count))

        # rationale
        action = summary_dict.get('action', 'HOLD')
        conf = summary_dict.get('confidence', 'trend')
        struct_enum = summary_dict.get('signals', {}).get('structure', 'none')
        seq_enum = summary_dict.get('signals', {}).get('sequence', 'none')

        rationale = self._compose_rationale(
            trend_label=trend_label,
            position_label=position_label,
            close=close,
            short_upper=trend_std.get('short_upper'),
            short_lower=trend_std.get('short_lower'),
            action=action,
            confidence=conf,
            structure=struct_enum,
            sequence=seq_enum,
        )

        return {
            'trend': {
                'label': trend_label,
                'position_label': position_label,
                'today_break_up': trend_std.get('short_upper'),
                'today_break_down': trend_std.get('short_lower'),
                'tomorrow_break_up': tomorrow_up,
                'tomorrow_break_down': tomorrow_dn,
            },
            'next_triggers': {
                'macd_75_at_close': struct_std.get('turn_price'),
                'macd_100_at_close': struct_std.get('cross_price'),
                'high9_progress': f'{h9_count}/9',
                'low9_progress': f'{l9_count}/9',
            },
            'rationale': rationale,
        }

    @staticmethod
    def _compose_rationale(*, trend_label, position_label, close,
                           short_upper, short_lower,
                           action, confidence, structure, sequence) -> str:
        """生成一句话总结。模板化，仅用数字与枚举，不做主观判断。"""
        parts = []
        if close is not None and short_upper is not None and short_lower is not None:
            if close > short_upper:
                pos_desc = f'收盘 {close} 高于短上轨 {short_upper}'
            elif close < short_lower:
                pos_desc = f'收盘 {close} 低于短下轨 {short_lower}'
            else:
                pos_desc = f'收盘 {close} 在短轨 [{short_lower}, {short_upper}] 区间内'
            parts.append(pos_desc)

        parts.append(f'趋势判定 {trend_label}（{position_label}）')

        if action == 'HOLD':
            parts.append('当前无新 BS 跃迁')
        else:
            parts.append(f'本根触发 {action}（{confidence} 置信度）')

        if structure != 'none':
            parts.append(f'结构事件：{structure}')
        if sequence != 'none':
            parts.append(f'九序事件：{sequence}')

        return '；'.join(parts) + '。'

    # ------------------------------------------------------------------ summary_integrated
    def summary_integrated(
        self,
        df_daily: pd.DataFrame,
        intraday: dict[str, pd.DataFrame],
    ) -> dict:
        """多周期整合快照（权威业务规则）：

        - **趋势**：仅使用日线 `df_daily` 计算仓位与 `standards.trend`。
        - **结构**：仅在 `60min` / `90min` / `120min` 上分别跑 MACD 结构，再合并
          `signals.structure*` / `standards.structure_by_period`；顶层 `signals.structure`
          取三周期中「事件强度最高」者，同分优先更短周期（60 > 90 > 120）。
        - **序列**：默认与日线同频（九转在日线收盘序列上计数），与文档「序列再次之」
          及当前产品默认一致；若以后单独指定序列周期可再扩展参数。

        `timestamp` / `close` / `execute_at` 对齐**日线最后一根**（T 日收盘视角）。
        """
        def _to_iso(v):
            if v is None or (isinstance(v, float) and np.isnan(v)) or pd.isna(v):
                return None
            try:
                return pd.Timestamp(v).isoformat()
            except Exception:
                return str(v)

        trend_thresholds = self.trend.next_day_thresholds(df_daily)

        trend_r = self.trend.evaluate(df_daily)
        seq_r = self.sequence.evaluate(df_daily)
        n_d = len(df_daily)
        if n_d == 0:
            return {'standards': {'trend': trend_thresholds, 'structure': {},
                                  'structure_by_period': {}}}

        pos = trend_r['position'].iloc[-1]
        prev = trend_r['position'].shift(1).iloc[-1]

        last_seq = seq_r.iloc[-1]

        exec_at = list(df_daily.index[1:]) + [pd.NaT]
        execute_at_last = exec_at[-1] if exec_at else pd.NaT

        # —— 各周期结构末行 ——
        struct_rows: dict[str, Optional[pd.Series]] = {k: None for k in STRUCTURE_INTERVAL_ORDER}
        for itv in STRUCTURE_INTERVAL_ORDER:
            df_i = intraday.get(itv)
            if df_i is None or len(df_i) < 30:
                continue
            ev = self.structure.evaluate(df_i)
            struct_rows[itv] = ev.iloc[-1]

        # 合并 active / until
        top_active_any = False
        bot_active_any = False
        until_candidates = []
        for itv in STRUCTURE_INTERVAL_ORDER:
            r = struct_rows[itv]
            if r is None:
                continue
            if bool(r.get('top_structure_active')):
                top_active_any = True
            if bool(r.get('bottom_structure_active')):
                bot_active_any = True
            if bool(r.get('top_structure_active')) or bool(r.get('bottom_structure_active')):
                u = r.get('structure_effective_until')
                if u is not None and pd.notna(u):
                    until_candidates.append(pd.Timestamp(u))

        structure_active = top_active_any or bot_active_any
        merged_until = max(until_candidates) if until_candidates else None

        # 竞争顶层 structure 枚举（强度优先，同分周期越短越好；忽略纯 none）
        best_enum = 'none'
        best_score = -1
        best_period: Optional[str] = None
        for itv in STRUCTURE_INTERVAL_ORDER:
            r = struct_rows[itv]
            if r is None:
                continue
            en = _structure_enum_from_row(r)
            sc = _STRUCTURE_ENUM_SCORE[en]
            if en == 'none':
                continue
            idx = STRUCTURE_INTERVAL_ORDER.index(itv)
            if sc > best_score:
                best_score, best_enum, best_period = sc, en, itv
            elif sc == best_score and best_period is not None:
                if idx < STRUCTURE_INTERVAL_ORDER.index(best_period):
                    best_enum, best_period = en, itv
            elif sc == best_score and best_period is None:
                best_enum, best_period = en, itv

        # per-period 信号块
        signals_by_period = {}
        standards_by_period = {}
        for itv in STRUCTURE_INTERVAL_ORDER:
            r = struct_rows[itv]
            if r is None:
                continue
            en_i = _structure_enum_from_row(r)
            signals_by_period[itv] = {
                'structure': en_i,
                'structure_active': bool(r.get('top_structure_active'))
                or bool(r.get('bottom_structure_active')),
                'structure_until': _to_iso(r.get('structure_effective_until')),
            }
            df_i = intraday[itv]
            th = self.structure.next_period_thresholds(df_i)
            standards_by_period[itv] = {
                'dif': th.get('dif'),
                'dea': th.get('dea'),
                'cross_price': th.get('macd_dif_cross_dea_price'),
                'turn_price': th.get('macd_dif_turn_price'),
            }

        # 顶层 structure 阈值：跟「竞争胜出周期」走；若无事件则退回首个可用周期
        ref_itv = best_period
        if ref_itv is None:
            for itv in STRUCTURE_INTERVAL_ORDER:
                if struct_rows[itv] is not None:
                    ref_itv = itv
                    break
        if ref_itv is not None and intraday.get(ref_itv) is not None:
            th0 = self.structure.next_period_thresholds(intraday[ref_itv])
            standards_structure = {
                'dif': th0.get('dif'),
                'dea': th0.get('dea'),
                'cross_price': th0.get('macd_dif_cross_dea_price'),
                'turn_price': th0.get('macd_dif_turn_price'),
                'reference_period': ref_itv,
            }
        else:
            standards_structure = {
                'dif': None, 'dea': None, 'cross_price': None, 'turn_price': None,
                'reference_period': None,
            }

        # —— BS 权重（与 evaluate 末行逻辑一致，但结构来自多周期合并）——
        if pd.isna(pos) or pd.isna(prev):
            action, weight, confidence = 'HOLD', 0.0, 'trend'
            core_long = core_short = False
            resonance_buy = resonance_sell = False
        else:
            delta = float(pos) - float(prev)
            if delta > 0:
                action = 'BUY'
                base_weight = delta / 10.0
            elif delta < 0:
                action = 'SELL'
                base_weight = -delta / 10.0
            else:
                action = 'HOLD'
                base_weight = 0.0

            bot_active = bot_active_any
            top_active = top_active_any
            bot_75_any = any(
                struct_rows[k] is not None and bool(struct_rows[k].get('bottom_structure_75'))
                for k in STRUCTURE_INTERVAL_ORDER)
            bot_100_any = any(
                struct_rows[k] is not None and bool(struct_rows[k].get('bottom_structure_100'))
                for k in STRUCTURE_INTERVAL_ORDER)
            top_75_any = any(
                struct_rows[k] is not None and bool(struct_rows[k].get('top_structure_75'))
                for k in STRUCTURE_INTERVAL_ORDER)
            top_100_any = any(
                struct_rows[k] is not None and bool(struct_rows[k].get('top_structure_100'))
                for k in STRUCTURE_INTERVAL_ORDER)

            core_long = (float(pos) >= 6.0) and bot_active
            core_short = (float(pos) <= 4.0) and top_active

            confidence = 'trend'
            weight = base_weight
            resonance_buy = resonance_sell = False

            if action == 'BUY' and core_long:
                mult = 1.5 if bot_100_any else 1.2 if bot_75_any else 1.2
                weight *= mult
                confidence = 'core'
                if bool(last_seq.get('low9_active')):
                    weight *= 1.2
                    confidence = 'resonance'
                    resonance_buy = True

            elif action == 'SELL' and core_short:
                mult = 1.5 if top_100_any else 1.2 if top_75_any else 1.2
                weight *= mult
                confidence = 'core'
                if bool(last_seq.get('high9_active')):
                    weight *= 1.2
                    confidence = 'resonance'
                    resonance_sell = True

            weight = round(float(weight), 6)

        pos_label = POSITION_LABEL.get(float(pos), '冷启动') if pd.notna(pos) else '冷启动'

        sequence_enum = 'none'
        if bool(last_seq.get('high9_signal')):
            sequence_enum = 'high9'
        elif bool(last_seq.get('low9_signal')):
            sequence_enum = 'low9'

        sequence_active = bool(last_seq.get('high9_active')) or bool(last_seq.get('low9_active'))

        resonance = None
        if structure_active:
            resonance = {'level': 1.0, 'periods': []}

        result = {
            'close': round(float(df_daily['Close'].iloc[-1]), 4)
            if pd.notna(df_daily['Close'].iloc[-1]) else None,
            'timestamp': pd.Timestamp(df_daily.index[-1]).isoformat(),
            'action': str(action),
            'weight': float(weight),
            'confidence': str(confidence),
            'execute_at': _to_iso(execute_at_last),
            'position': {
                'current': float(pos) if pd.notna(pos) else None,
                'prev': float(prev) if pd.notna(prev) else None,
                'label': pos_label,
            },
            'signals': {
                'structure': best_enum,
                'structure_active': structure_active,
                'structure_until': _to_iso(merged_until),
                'structure_by_period': signals_by_period,
                'sequence': sequence_enum,
                'sequence_active': sequence_active,
                'sequence_until': _to_iso(last_seq.get('sequence_effective_until')),
                'resonance': resonance,
                'probe': False,
            },
            'standards': {
                'trend': trend_thresholds,
                'structure': {k: v for k, v in standards_structure.items()
                              if k != 'reference_period'},
                'structure_reference_period': standards_structure.get('reference_period'),
                'structure_by_period': standards_by_period,
            },
        }

        # view：趋势只看日线；结构触发价列出三周期
        trend_label = self._POSITION_TO_TREND_LABEL.get(float(pos), '冷启动') \
            if pos is not None and pd.notna(pos) else '冷启动'
        tomorrow_up = self._extrapolate_next(self.trend.compute_all(df_daily)['short_upper'])
        tomorrow_dn = self._extrapolate_next(self.trend.compute_all(df_daily)['short_lower'])
        h9_count = int(last_seq['high9_count']) if 'high9_count' in last_seq.index else 0
        l9_count = int(last_seq['low9_count']) if 'low9_count' in last_seq.index else 0
        h9_count = max(0, min(9, h9_count))
        l9_count = max(0, min(9, l9_count))

        by_period_triggers = {}
        for itv, st in standards_by_period.items():
            by_period_triggers[itv] = {
                'macd_75_at_close': st.get('turn_price'),
                'macd_100_at_close': st.get('cross_price'),
            }

        rationale = self._compose_rationale(
            trend_label=trend_label,
            position_label=pos_label,
            close=result['close'],
            short_upper=trend_thresholds.get('short_upper'),
            short_lower=trend_thresholds.get('short_lower'),
            action=action,
            confidence=confidence,
            structure=best_enum,
            sequence=sequence_enum,
        )

        result['view'] = {
            'trend': {
                'label': trend_label,
                'position_label': pos_label,
                'source': 'daily',
                'today_break_up': trend_thresholds.get('short_upper'),
                'today_break_down': trend_thresholds.get('short_lower'),
                'tomorrow_break_up': tomorrow_up,
                'tomorrow_break_down': tomorrow_dn,
            },
            'next_triggers': {
                'macd_75_at_close': standards_structure.get('turn_price'),
                'macd_100_at_close': standards_structure.get('cross_price'),
                'structure_reference_period': standards_structure.get('reference_period'),
                'by_period': by_period_triggers,
                'high9_progress': f'{h9_count}/9',
                'low9_progress': f'{l9_count}/9',
                'sequence_source': 'daily',
            },
            'rationale': rationale,
        }

        return result

    # ------------------------------------------------------------------ summary
    def summary(self, df: pd.DataFrame) -> dict:
        """把最新一根 K 线打包为 API 响应字典（与 api.md `/stock/decision` 对齐）。

        多周期共振 `signals.resonance` 留给上层（analysis_service）注入，
        本函数仅根据当前周期填出单周期视角。
        """
        trend_thresholds = self.trend.next_day_thresholds(df)
        struct_thresholds = self.structure.next_period_thresholds(df)

        # 阈值统一改名（API 契约）
        standards_structure = {
            'dif': struct_thresholds.get('dif'),
            'dea': struct_thresholds.get('dea'),
            'cross_price': struct_thresholds.get('macd_dif_cross_dea_price'),
            'turn_price': struct_thresholds.get('macd_dif_turn_price'),
        }

        decision = self.evaluate(df)

        # 取最后一行（即使 position 为 NaN，仍要返回基本信息）
        if len(decision) == 0:
            return {
                'standards': {'trend': trend_thresholds, 'structure': standards_structure},
            }

        last = decision.iloc[-1]

        # 结构枚举
        structure_enum = 'none'
        if bool(last.get('top_structure_100')):
            structure_enum = 'top_100'
        elif bool(last.get('top_structure_75')):
            structure_enum = 'top_75'
        elif bool(last.get('bottom_structure_100')):
            structure_enum = 'bottom_100'
        elif bool(last.get('bottom_structure_75')):
            structure_enum = 'bottom_75'

        # 序列枚举
        sequence_enum = 'none'
        if bool(last.get('high9_signal')):
            sequence_enum = 'high9'
        elif bool(last.get('low9_signal')):
            sequence_enum = 'low9'

        structure_active = bool(last.get('top_structure_active')) or bool(last.get('bottom_structure_active'))
        sequence_active = bool(last.get('high9_active')) or bool(last.get('low9_active'))

        structure_until = last.get('structure_effective_until')
        sequence_until = last.get('sequence_effective_until')

        def _to_iso(v):
            if v is None or (isinstance(v, float) and np.isnan(v)) or pd.isna(v):
                return None
            try:
                return pd.Timestamp(v).isoformat()
            except Exception:
                return str(v)

        pos = last.get('position')
        prev = last.get('prev_position')
        label = last.get('position_label') or '冷启动'

        # resonance：单周期视角 — 若结构 active 则 periods 含当前 interval；
        # 多周期共振由上层 analysis_service 合并后覆盖
        resonance = None
        if structure_active:
            resonance = {'level': 1.0, 'periods': []}

        result = {
            'close': round(float(last['Close']), 4) if pd.notna(last.get('Close')) else None,
            'timestamp': pd.Timestamp(last.name).isoformat() if hasattr(last, 'name') and last.name is not None else None,
            'action': str(last.get('action', 'HOLD')),
            'weight': float(last.get('weight', 0.0)),
            'confidence': str(last.get('confidence', 'trend')),
            'execute_at': _to_iso(last.get('execute_at')),
            'position': {
                'current': float(pos) if pd.notna(pos) else None,
                'prev': float(prev) if pd.notna(prev) else None,
                'label': str(label),
            },
            'signals': {
                'structure': structure_enum,
                'structure_active': structure_active,
                'structure_until': _to_iso(structure_until),
                'sequence': sequence_enum,
                'sequence_active': sequence_active,
                'sequence_until': _to_iso(sequence_until),
                'resonance': resonance,
                'probe': bool(last.get('probe', False)),
            },
            'standards': {
                'trend': trend_thresholds,
                'structure': standards_structure,
            },
        }

        # ---- view 派生层：把 standards 里的关键数值翻译为"人话" ----
        # 需要原始 sequence DataFrame 才能拿 *_count；直接重跑序列拿到（开销极小）
        seq_df = self.sequence.evaluate(df)
        struct_df = self.structure.evaluate(df)
        result['view'] = self._make_view(decision, result, struct_df, seq_df)

        return result
