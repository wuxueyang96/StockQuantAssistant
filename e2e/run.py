#!/usr/bin/env python3
"""
E2E 测试脚本 — 以阿里巴巴 / 阳光电源为例，完整运行所有 API
用法: python3 e2e/run.py
"""

import os
import sys
import json
import tempfile
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS = 0
FAIL = 0
RESULTS = []


def setup():
    tmpdir = tempfile.mkdtemp(prefix='stockquant_e2e_')
    from app.config import Config
    Config.DATA_DIR = tmpdir
    Config.OSS_BUCKET = None
    return tmpdir


def record(passed, label, detail=''):
    global PASS, FAIL
    if passed:
        PASS += 1
        RESULTS.append(f'  ✅  {label}')
    else:
        FAIL += 1
        RESULTS.append(f'  ❌  {label}')
        if detail:
            RESULTS.append(f'      {detail}')


def run():
    global PASS, FAIL

    print('=' * 60)
    print(' StockQuantAssisant E2E 测试 — 阿里巴巴 / 阳光电源')
    print('=' * 60)

    tmpdir = setup()
    print(f'\n📁 临时数据目录: {tmpdir}')

    from app import create_app
    from app.models.database import db_manager

    app = create_app()
    app.config['TESTING'] = True
    client = app.test_client()

    def post(path, data=None):
        return client.post(path, json=data)

    def get(path):
        return client.get(path)

    def delete(path):
        return client.delete(path)

    # ─────────────────────────────────────────────
    print('\n📋 阶段 1: 健康检查')
    # ─────────────────────────────────────────────
    resp = get('/api/health')
    ok = resp.status_code == 200
    body = resp.get_json() if ok else {}
    record(ok and body.get('status') == 'ok',
           f'GET /api/health → {resp.status_code}')

    # ─────────────────────────────────────────────
    print('\n📋 阶段 2: 股票代码映射')
    # ─────────────────────────────────────────────

    # 2.1 录入阿里巴巴 (hk + us)
    resp = post('/api/stock/code', {'name': '阿里巴巴', 'hk': '09988', 'us': 'BABA'})
    body = resp.get_json()
    record(resp.status_code == 200 and body.get('success'),
           f'POST /api/stock/code (阿里巴巴) → {resp.status_code}')

    # 2.2 录入阳光电源 (A 股)
    resp = post('/api/stock/code', {'name': '阳光电源', 'a': '300274'})
    body = resp.get_json()
    record(resp.status_code == 200 and body.get('success'),
           f'POST /api/stock/code (阳光电源) → {resp.status_code}')

    # 2.3 录入贵州茅台
    resp = post('/api/stock/code', {'name': '贵州茅台', 'a': '600519'})
    body = resp.get_json()
    record(resp.status_code == 200 and body.get('success'),
           f'POST /api/stock/code (贵州茅台) → {resp.status_code}')

    # 2.4 缺少 name
    resp = post('/api/stock/code', {})
    record(resp.status_code == 400,
           f'POST /api/stock/code (缺 name) → {resp.status_code}')

    # 2.5 缺少市场代码
    resp = post('/api/stock/code', {'name': 'test'})
    record(resp.status_code == 400,
           f'POST /api/stock/code (缺市场) → {resp.status_code}')

    # 2.6 查看所有映射
    resp = get('/api/stock/codes')
    body = resp.get_json()
    ok = resp.status_code == 200 and body.get('success') and body.get('count') >= 3
    record(ok, f'GET /api/stock/codes → count={body.get("count")}')

    # ─────────────────────────────────────────────
    print('\n📋 阶段 3: 工作流注册')
    # ─────────────────────────────────────────────

    # 3.1 注册 阿里巴巴（多市场: hk + us → 应创建 8 个工作流）
    resp = post('/api/stock/register', {'stock': '阿里巴巴'})
    body = resp.get_json()
    wf_count = len(body.get('workflows', []))
    mk_count = len(body.get('markets', []))
    ok = resp.status_code == 200 and wf_count == 8 and mk_count == 2
    record(ok, f'POST /api/stock/register (阿里巴巴) → {wf_count} workflows, {mk_count} markets',
           f'workflows={body.get("workflows")}')

    # 3.2 注册 阳光电源（A 股名称 → 4 个工作流）
    resp = post('/api/stock/register', {'stock': '阳光电源'})
    body = resp.get_json()
    mk_count = len(body.get('markets', []))
    ok = resp.status_code == 200 and '已创建' in body.get('message', '') and mk_count == 1
    record(ok, f'POST /api/stock/register (阳光电源) → {body.get("message")} ({mk_count} market)')

    # 3.3 重复注册（应返回已存在）
    resp = post('/api/stock/register', {'stock': '阿里巴巴'})
    body = resp.get_json()
    ok = resp.status_code == 200 and '已存在' in body.get('message', '')
    record(ok, f'POST /api/stock/register (重复) → {body.get("message")}')

    # 3.4 注册 000001（A 股代码）
    resp = post('/api/stock/register', {'stock': '000001'})
    body = resp.get_json()
    ok = resp.status_code == 200 and '已创建' in body.get('message', '')
    record(ok, f'POST /api/stock/register (000001) → {body.get("message")}')

    # 3.5 注册 00700.HK（港股代码带后缀）
    resp = post('/api/stock/register', {'stock': '00700.HK'})
    body = resp.get_json()
    ok = resp.status_code == 200 and '已创建' in body.get('message', '')
    record(ok, f'POST /api/stock/register (00700.HK) → {body.get("message")}')

    # 3.6 注册 AAPL（美股代码）
    resp = post('/api/stock/register', {'stock': 'AAPL'})
    body = resp.get_json()
    ok = resp.status_code == 200 and '已创建' in body.get('message', '')
    record(ok, f'POST /api/stock/register (AAPL) → {body.get("message")}')

    # 3.7 缺少参数
    resp = post('/api/stock/register', {})
    record(resp.status_code == 400, f'POST /api/stock/register (缺参) → {resp.status_code}')

    # ─────────────────────────────────────────────
    print('\n📋 阶段 4: 工作流查询')
    # ─────────────────────────────────────────────

    # 4.1 按代码查询 09988
    resp = get('/api/stock/09988/workflows')
    body = resp.get_json()
    ok = resp.status_code == 200 and len(body.get('workflows', [])) == 4
    record(ok, f'GET /api/stock/09988/workflows → {len(body.get("workflows", []))} workflows')

    # 4.2 查询 BABA
    resp = get('/api/stock/BABA/workflows')
    body = resp.get_json()
    ok = resp.status_code == 200 and len(body.get('workflows', [])) == 4
    record(ok, f'GET /api/stock/BABA/workflows → {len(body.get("workflows", []))} workflows')

    # 4.3 查询 300274 (阳光电源)
    resp = get('/api/stock/300274/workflows')
    body = resp.get_json()
    ok = resp.status_code == 200 and len(body.get('workflows', [])) == 4
    record(ok, f'GET /api/stock/300274/workflows → {len(body.get("workflows", []))} workflows')

    # 4.4 查询所有工作流
    resp = get('/api/workflows')
    body = resp.get_json()
    total = body.get('count', 0)
    record(total >= 20, f'GET /api/workflows → count={total}')

    # ─────────────────────────────────────────────
    print('\n📋 阶段 5: 量化决策')
    # ─────────────────────────────────────────────

    # 5.1 阿里巴巴多市场决策
    resp = post('/api/stock/decision', {'stock': '阿里巴巴'})
    body = resp.get_json()
    ok = resp.status_code == 200 and body.get('success') and body.get('count') == 2
    record(ok, f'POST /api/stock/decision (阿里巴巴) → {body.get("count")} markets')
    for r in body.get('results', []):
        if 'error' in r:
            RESULTS.append(f'      [{r["market"]}] {r["error"]}')
        else:
            ts = r.get('trend_standard', {})
            ss = r.get('structure_standard', {})
            RESULTS.append(f'      [{r["market"]}] pos={r["position"]}({r["position_label"]}) '
                           f'close={r["close"]} core_long={r["core_long"]} core_short={r["core_short"]}')
            RESULTS.append(f'        trend: short_up={ts.get("short_upper")} long_up={ts.get("long_upper")}')
            RESULTS.append(f'        struct: dif={ss.get("dif")} dea={ss.get("dea")} '
                           f'cross_dea_price={ss.get("macd_dif_cross_dea_price")}')
            # 验证新字段存在
            assert 'trend_standard' in r, f'[{r["market"]}] 缺少 trend_standard'
            assert 'structure_standard' in r, f'[{r["market"]}] 缺少 structure_standard'
            assert 'short_upper' in ts, f'[{r["market"]}] trend_standard 缺少 short_upper'
            assert 'long_upper' in ts, f'[{r["market"]}] trend_standard 缺少 long_upper'
            assert 'macd_dif_cross_dea_price' in ss, f'[{r["market"]}] structure_standard 缺少 macd_dif_cross_dea_price'

    # 5.2 阳光电源决策
    resp = post('/api/stock/decision', {'stock': '阳光电源'})
    body = resp.get_json()
    ok = resp.status_code == 200 and body.get('success') and body.get('count') == 1
    record(ok, f'POST /api/stock/decision (阳光电源) → {body.get("count")} market')
    for r in body.get('results', []):
        if 'error' in r:
            RESULTS.append(f'      [{r["market"]}] {r["error"]}')
            record(False, f'阳光电源决策失败', r['error'])
        else:
            ts = r.get('trend_standard', {})
            ss = r.get('structure_standard', {})
            RESULTS.append(f'      [{r["market"]}] pos={r["position"]}({r["position_label"]}) '
                           f'close={r["close"]}')
            RESULTS.append(f'        trend: short_up={ts.get("short_upper")} long_up={ts.get("long_upper")}')
            RESULTS.append(f'        struct: dif={ss.get("dif")} dea={ss.get("dea")} '
                           f'cross_dea_price={ss.get("macd_dif_cross_dea_price")}')
            assert 'trend_standard' in r
            assert 'structure_standard' in r
            assert isinstance(ts.get('short_upper'), (int, float, type(None)))
            assert isinstance(ss.get('macd_dif_cross_dea_price'), (int, float, type(None)))

    # 5.3 000001 决策
    resp = post('/api/stock/decision', {'stock': '000001'})
    body = resp.get_json()
    ok = resp.status_code == 200 and body.get('success')
    record(ok, f'POST /api/stock/decision (000001) → {resp.status_code}')
    for r in body.get('results', []):
        if 'error' in r:
            RESULTS.append(f'      [{r["market"]}] {r["error"]}')
        else:
            RESULTS.append(f'      [{r["market"]}] pos={r["position"]}({r["position_label"]})')

    # 5.4 AAPL 决策
    resp = post('/api/stock/decision', {'stock': 'AAPL'})
    body = resp.get_json()
    ok = resp.status_code == 200 and body.get('success')
    record(ok, f'POST /api/stock/decision (AAPL) → {resp.status_code}')
    for r in body.get('results', []):
        if 'error' in r:
            RESULTS.append(f'      [{r["market"]}] {r["error"]}')
        else:
            RESULTS.append(f'      [{r["market"]}] pos={r["position"]}({r["position_label"]}) close={r["close"]}')

    # 5.5 不存在的名称
    resp = post('/api/stock/decision', {'stock': '不存在的股票'})
    record(resp.status_code == 400, f'POST /api/stock/decision (不存在) → {resp.status_code}')

    # 5.6 缺少参数
    resp = post('/api/stock/decision', {})
    record(resp.status_code == 400, f'POST /api/stock/decision (缺参) → {resp.status_code}')

    # 5.7 无效周期
    resp = post('/api/stock/decision', {'stock': '000001', 'interval': '5min'})
    record(resp.status_code == 400, f'POST /api/stock/decision (无效 interval) → {resp.status_code}')

    # ─────────────────────────────────────────────
    print('\n📋 阶段 6: 工作流删除')
    # ─────────────────────────────────────────────

    # 6.1 删除一个工作流
    before = get('/api/workflows').get_json().get('count', 0)
    resp = delete('/api/workflows/US_BABA.US_90min')
    after = get('/api/workflows').get_json().get('count', 0)
    ok = resp.status_code == 200 and after == before - 1
    record(ok, f'DELETE /api/workflows/US_BABA.US_90min → before={before} after={after}')

    # 6.2 删除不存在的工作流
    resp = delete('/api/workflows/NONEXISTENT_workflow')
    record(resp.status_code == 404, f'DELETE /api/workflows/NONEXISTENT → {resp.status_code}')

    # ─────────────────────────────────────────────
    print('\n📋 阶段 7: 持久化验证')
    # ─────────────────────────────────────────────

    # 7.1 验证 workflows 表中有数据
    wf_db_count = db_manager._get_metadata_conn().execute(
        "SELECT COUNT(*) FROM workflows"
    ).fetchone()[0]
    record(wf_db_count >= 19, f'metadata.db.workflows 行数 = {wf_db_count}')

    # 7.2 验证 stock_codes 表
    sc_count = db_manager._get_metadata_conn().execute(
        "SELECT COUNT(*) FROM stock_codes"
    ).fetchone()[0]
    record(sc_count >= 3, f'metadata.db.stock_codes 行数 = {sc_count}')

    # 7.3 验证工作流恢复
    from app.services.workflow_service import WorkflowService
    new_ws = WorkflowService()
    reload_count = len(new_ws.workflows)
    record(reload_count == after, f'工作流恢复: 预期 {after}, 实际 {reload_count}')

    # ─────────────────────────────────────────────
    # 清理
    # ─────────────────────────────────────────────
    db_manager.close_all()

    # ─────────────────────────────────────────────
    print(f'\n{"=" * 60}')
    print(f' 结果: {PASS} 通过 / {FAIL} 失败 / {PASS + FAIL} 总计')
    print(f'{"=" * 60}')

    for r in RESULTS:
        print(r)

    print(f'\n🧹 临时数据已清理: {tmpdir}')
    return FAIL == 0


if __name__ == '__main__':
    success = run()
    sys.exit(0 if success else 1)
