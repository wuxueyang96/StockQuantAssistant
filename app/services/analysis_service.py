import logging
from typing import Optional
import pandas as pd
from app.services.stock_service import detect_market, get_table_name, format_stock_code, MARKET_LABEL
from app.models.database import db_manager
from app.algos.decision import DecisionEngine

logger = logging.getLogger(__name__)
_engine = DecisionEngine()

POSITION_LABELS = {10.0: '满仓', 6.0: '重仓', 4.0: '轻仓', 0.0: '空仓'}


def analyze_stock(stock_input: str, interval: str = 'daily') -> dict:
    detections = detect_market(stock_input)

    results = []
    for market, stock_code in detections:
        table_name = get_table_name(market, stock_code, interval)
        display_code = format_stock_code(market, stock_code)

        df = db_manager.get_data(market, table_name, limit=500)
        if df is None or df.empty:
            results.append({
                'market': market,
                'stock_code': stock_code,
                'display_code': display_code,
                'error': f'数据表 {table_name} 不存在或为空，请先注册该股票工作流',
            })
            continue

        df = df.set_index('timestamp') if 'timestamp' in df.columns else df
        df = df.sort_index()
        df = df.rename(columns={c: c.capitalize() for c in df.columns})

        if 'Close' not in df.columns:
            if 'close' in df.columns:
                df = df.rename(columns={c: c.capitalize() for c in df.columns})

        try:
            summary = _engine.summary(df)
        except Exception as e:
            logger.error(f"决策引擎执行失败 ({market}/{stock_code}): {e}")
            results.append({
                'market': market,
                'stock_code': stock_code,
                'display_code': display_code,
                'error': f'算法计算失败: {str(e)}',
            })
            continue

        pos = summary.get('position')
        pos_label = POSITION_LABELS.get(pos, '未定')

        latest = {
            'market': market,
            'market_label': MARKET_LABEL[market],
            'stock_code': stock_code,
            'display_code': display_code,
            'timestamp': summary.get('timestamp'),
            'close': summary.get('close'),
            'position': pos,
            'position_label': pos_label,
            'core_long': summary.get('core_long', False),
            'core_short': summary.get('core_short', False),
            'resonance_buy': summary.get('resonance_buy', False),
            'resonance_sell': summary.get('resonance_sell', False),
            'top_structure_75': summary.get('top_structure_75', False),
            'top_structure_100': summary.get('top_structure_100', False),
            'bottom_structure_75': summary.get('bottom_structure_75', False),
            'bottom_structure_100': summary.get('bottom_structure_100', False),
            'high9_signal': summary.get('high9_signal', False),
            'low9_signal': summary.get('low9_signal', False),
            'trend_standard': summary.get('trend_standard', {}),
            'structure_standard': summary.get('structure_standard', {}),
        }

        # history
        decision = _engine.evaluate(df)
        if 'position' in decision.columns:
            pos_series = decision['position'].dropna()
            if len(pos_series) > 0:
                latest['position_history'] = {
                    'current': float(pos_series.iloc[-1]) if pd.notna(pos_series.iloc[-1]) else None,
                    'prev': float(pos_series.iloc[-2]) if len(pos_series) > 1 and pd.notna(pos_series.iloc[-2]) else None,
                }

        results.append(latest)

    return {
        'success': True,
        'input': stock_input,
        'interval': interval,
        'count': len(results),
        'results': results,
    }
