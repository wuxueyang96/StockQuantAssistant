import pandas as pd
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
