import pandas as pd
import numpy as np


class NineSequence:
    def evaluate(self, df: pd.DataFrame) -> pd.DataFrame:
        result = df.copy()
        n = len(result)

        result['high9_count'] = 0
        result['low9_count'] = 0
        result['high9_signal'] = False
        result['low9_signal'] = False

        if n < 9:
            return result

        high9_count = 0
        low9_count = 0

        for i in range(4, n):
            close_cur = result['Close'].iloc[i]
            close_prev4 = result['Close'].iloc[i - 4]

            if close_cur > close_prev4:
                high9_count += 1
            else:
                high9_count = 0

            if close_cur < close_prev4:
                low9_count += 1
            else:
                low9_count = 0

            result.at[result.index[i], 'high9_count'] = high9_count
            result.at[result.index[i], 'low9_count'] = low9_count

            if high9_count == 9:
                bar8 = i - 1
                bar9 = i
                bar6 = i - 3
                bar7 = i - 2
                high_89 = max(result['High'].iloc[bar8], result['High'].iloc[bar9])
                high_67 = max(result['High'].iloc[bar6], result['High'].iloc[bar7])
                if high_89 > high_67:
                    result.at[result.index[i], 'high9_signal'] = True

            if low9_count == 9:
                bar8 = i - 1
                bar9 = i
                bar6 = i - 3
                bar7 = i - 2
                low_89 = min(result['Low'].iloc[bar8], result['Low'].iloc[bar9])
                low_67 = min(result['Low'].iloc[bar6], result['Low'].iloc[bar7])
                if low_89 < low_67:
                    result.at[result.index[i], 'low9_signal'] = True

        return result
