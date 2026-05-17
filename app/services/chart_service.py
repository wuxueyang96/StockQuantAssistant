"""把 OHLCV + 趋势通道 / MACD 画成 PNG。

- `render_chart_png`：单周期 K 线 + 趋势四轨（TrendChannel）。
- `render_intraday_macd_png`：K 线 + 下方 MACD(DIF/DEA) 面板，用于 60/90/120 结构视角。
- `render_integrated_dashboard_png`：纵向拼接「日线趋势 + 三周期结构」，落实「趋势只看日线、结构看 60/90/120」。
"""
from __future__ import annotations

import io
import logging
from typing import Optional

import matplotlib

matplotlib.use('Agg')   # 服务端无 X11，先切到非交互后端
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.lines import Line2D
import mplfinance as mpf
import pandas as pd

from app.algos.structure import MACDStructure
from app.algos.trend import TrendChannel

logger = logging.getLogger(__name__)


def _resolve_chinese_font() -> Optional[str]:
    candidates = [
        'WenQuanYi Zen Hei', 'WenQuanYi Micro Hei', 'Noto Sans CJK SC',
        'Source Han Sans CN', 'PingFang SC', 'Microsoft YaHei',
        'SimHei', 'Heiti TC', 'AR PL UMing CN',
    ]
    from matplotlib import font_manager
    available = {f.name for f in font_manager.fontManager.ttflist}
    for name in candidates:
        if name in available:
            return name
    return None


_CN_FONT = _resolve_chinese_font()
if _CN_FONT:
    matplotlib.rcParams['font.sans-serif'] = [_CN_FONT, 'DejaVu Sans']
    matplotlib.rcParams['axes.unicode_minus'] = False


def render_chart_png(
    df: pd.DataFrame,
    title: str = '',
    channels_df: Optional[pd.DataFrame] = None,
    bars: int = 120,
) -> bytes:
    """渲染 K 线 + 趋势通道图，返回 PNG 字节流。"""
    if df is None or len(df) == 0:
        raise ValueError('render_chart_png: empty OHLCV input')

    df = df.sort_index().copy()
    needed_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
    for col in needed_cols:
        if col not in df.columns:
            raise ValueError(f'render_chart_png: missing column {col}')

    if channels_df is None:
        channels_df = TrendChannel().compute_all(df)

    df_tail = df.tail(bars)
    ch_tail = channels_df.loc[df_tail.index]

    addplots = [
        mpf.make_addplot(ch_tail['short_upper'], color='#e74c3c', width=1.0),
        mpf.make_addplot(ch_tail['short_lower'], color='#27ae60', width=1.0),
        mpf.make_addplot(ch_tail['long_upper'],  color='#c0392b', width=0.8, linestyle='--'),
        mpf.make_addplot(ch_tail['long_lower'],  color='#16a085', width=0.8, linestyle='--'),
    ]

    style = mpf.make_mpf_style(
        base_mpf_style='charles',
        rc={'font.family': matplotlib.rcParams['font.sans-serif']} if _CN_FONT else {},
    )

    buf = io.BytesIO()
    fig, axlist = mpf.plot(
        df_tail,
        type='candle',
        style=style,
        addplot=addplots,
        volume=False,
        figsize=(12, 6),
        title=title,
        returnfig=True,
        tight_layout=True,
    )
    # mplfinance 不把 addplot 自动进图例，用代理线说明四轨（与 TrendChannel 默认 26/90 一致）
    ax_main = axlist[0] if isinstance(axlist, (list, tuple)) else axlist
    legend_handles = [
        Line2D([0], [0], color='#e74c3c', linewidth=2, linestyle='-', label='短期上轨（26 日窗口）'),
        Line2D([0], [0], color='#27ae60', linewidth=2, linestyle='-', label='短期下轨（26 日窗口）'),
        Line2D([0], [0], color='#c0392b', linewidth=2, linestyle='--', label='长期上轨（90 日窗口）'),
        Line2D([0], [0], color='#16a085', linewidth=2, linestyle='--', label='长期下轨（90 日窗口）'),
    ]
    legend_kw: dict = {
        'handles': legend_handles,
        'loc': 'upper left',
        'framealpha': 0.92,
        'title': '趋势通道',
    }
    if _CN_FONT:
        legend_kw['prop'] = font_manager.FontProperties(family=_CN_FONT, size=8)
        legend_kw['title_fontproperties'] = font_manager.FontProperties(
            family=_CN_FONT, size=9,
        )
    else:
        legend_kw['fontsize'] = 8
    leg = ax_main.legend(**legend_kw)
    if leg.get_title() is not None and not _CN_FONT:
        leg.get_title().set_fontsize(9)

    fig.savefig(buf, format='png', dpi=120, bbox_inches='tight')
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def render_intraday_macd_png(
    df: pd.DataFrame,
    title: str = '',
    bars: int = 120,
) -> bytes:
    """K 线 + MACD(DIF/DEA) 副图，用于 60/90/120 分钟结构观察。"""
    if df is None or len(df) == 0:
        raise ValueError('render_intraday_macd_png: empty OHLCV input')

    df = df.sort_index().copy()
    for col in ('Open', 'High', 'Low', 'Close', 'Volume'):
        if col not in df.columns:
            raise ValueError(f'render_intraday_macd_png: missing column {col}')

    df_tail = df.tail(bars)
    macd = MACDStructure().compute_macd(df)
    macd_tail = macd.reindex(df_tail.index)

    addplots = [
        mpf.make_addplot(macd_tail['dif'], panel=1, color='#2980b9', width=1.0, ylabel='MACD'),
        mpf.make_addplot(macd_tail['dea'], panel=1, color='#e67e22', width=1.0),
    ]

    style = mpf.make_mpf_style(
        base_mpf_style='charles',
        rc={'font.family': matplotlib.rcParams['font.sans-serif']} if _CN_FONT else {},
    )

    buf = io.BytesIO()
    fig, _ = mpf.plot(
        df_tail,
        type='candle',
        style=style,
        addplot=addplots,
        volume=False,
        figsize=(12, 5),
        title=title,
        returnfig=True,
        tight_layout=True,
        panel_ratios=(3, 1),
    )
    fig.savefig(buf, format='png', dpi=110, bbox_inches='tight')
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def render_integrated_dashboard_png(
    df_daily: pd.DataFrame,
    intraday: dict[str, pd.DataFrame],
    title_daily: str,
    intraday_titles: Optional[dict[str, str]] = None,
    bars: int = 90,
) -> bytes:
    """纵向拼接：日线（K+趋势四轨） + 各有的 60/90/120（K+MACD）。"""
    try:
        from PIL import Image
    except ImportError as e:
        raise RuntimeError('需要 pillow 以拼接整合图') from e

    intraday_titles = intraday_titles or {}
    order = ('60min', '90min', '120min')
    chunks: list[bytes] = [
        render_chart_png(df_daily, title=title_daily, bars=bars),
    ]
    for itv in order:
        dfi = intraday.get(itv)
        if dfi is not None and len(dfi) >= 30:
            ttl = intraday_titles.get(itv, f'{itv} + MACD')
            chunks.append(render_intraday_macd_png(dfi, title=ttl, bars=bars))

    images = [Image.open(io.BytesIO(b)) for b in chunks]
    w = max(im.width for im in images)
    resized = []
    for im in images:
        if im.width != w:
            nh = max(1, int(im.height * w / im.width))
            im = im.resize((w, nh), Image.Resampling.LANCZOS)
        resized.append(im)

    gap = 8
    total_h = sum(im.height for im in resized) + gap * (len(resized) - 1)
    canvas = Image.new('RGB', (w, total_h), (255, 255, 255))
    y = 0
    for im in resized:
        canvas.paste(im, (0, y))
        y += im.height + gap

    buf = io.BytesIO()
    canvas.save(buf, format='PNG', optimize=True)
    return buf.getvalue()
