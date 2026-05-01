import pandas as pd
import numpy as np
from app.algos.trend import TrendChannel
from app.algos.structure import MACDStructure
from app.algos.sequence import NineSequence


class DecisionEngine:
    def __init__(self, trend=None, structure=None, sequence=None):
        self.trend = trend or TrendChannel()
        self.structure = structure or MACDStructure()
        self.sequence = sequence or NineSequence()

    def evaluate(self, df: pd.DataFrame) -> pd.DataFrame:
        trend_result = self.trend.evaluate(df)
        structure_result = self.structure.evaluate(df)
        sequence_result = self.sequence.evaluate(df)

        result = df.copy()
        result['position'] = trend_result['position']

        result['top_structure_75'] = structure_result['top_structure_75']
        result['top_structure_100'] = structure_result['top_structure_100']
        result['bottom_structure_75'] = structure_result['bottom_structure_75']
        result['bottom_structure_100'] = structure_result['bottom_structure_100']
        result['high9_signal'] = sequence_result['high9_signal']
        result['low9_signal'] = sequence_result['low9_signal']

        result['core_long'] = False
        result['core_short'] = False
        result['resonance_buy'] = False
        result['resonance_sell'] = False

        n = len(result)
        for i in range(n):
            pos = result.loc[result.index[i], 'position']
            if pd.isna(pos):
                continue

            bottom_75 = result.loc[result.index[i], 'bottom_structure_75']
            bottom_100 = result.loc[result.index[i], 'bottom_structure_100']
            top_75 = result.loc[result.index[i], 'top_structure_75']
            top_100 = result.loc[result.index[i], 'top_structure_100']
            high9 = result.loc[result.index[i], 'high9_signal']
            low9 = result.loc[result.index[i], 'low9_signal']

            if pos >= 4.0 and (bottom_75 or bottom_100):
                result.at[result.index[i], 'core_long'] = True

            if pos <= 6.0 and (top_75 or top_100):
                result.at[result.index[i], 'core_short'] = True

            if result.loc[result.index[i], 'core_long'] and low9:
                result.at[result.index[i], 'resonance_buy'] = True

            if result.loc[result.index[i], 'core_short'] and high9:
                result.at[result.index[i], 'resonance_sell'] = True

        return result

    def summary(self, df: pd.DataFrame) -> dict:
        """返回最新决策摘要，包含下一交易日的趋势量化标准和结构量化标准。"""
        trend_thresholds = self.trend.next_day_thresholds(df)
        structure_thresholds = self.structure.next_period_thresholds(df)

        decision = self.evaluate(df)
        last = decision.dropna(subset=['position'])
        if last.empty:
            return {
                'trend_standard': trend_thresholds,
                'structure_standard': structure_thresholds,
            }
        last = last.iloc[-1]

        pos = last.get('position')
        return {
            'position': float(pos) if pd.notna(pos) else None,
            'core_long': bool(last.get('core_long', False)),
            'core_short': bool(last.get('core_short', False)),
            'resonance_buy': bool(last.get('resonance_buy', False)),
            'resonance_sell': bool(last.get('resonance_sell', False)),
            'top_structure_75': bool(last.get('top_structure_75', False)),
            'top_structure_100': bool(last.get('top_structure_100', False)),
            'bottom_structure_75': bool(last.get('bottom_structure_75', False)),
            'bottom_structure_100': bool(last.get('bottom_structure_100', False)),
            'high9_signal': bool(last.get('high9_signal', False)),
            'low9_signal': bool(last.get('low9_signal', False)),
            'close': round(float(last.get('Close', 0)), 4) if pd.notna(last.get('Close')) else None,
            'timestamp': str(last.name) if hasattr(last, 'name') else None,
            'trend_standard': trend_thresholds,
            'structure_standard': structure_thresholds,
        }
