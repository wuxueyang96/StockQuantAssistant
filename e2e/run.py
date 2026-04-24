#!/usr/bin/env python3
"""
E2E 测试脚本 — 以阿里巴巴为例，完整运行所有 API
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
    Config.METADATA_DB_PATH = os.path.join(tmpdir, 'metadata.db')
    Config.DB_PATHS = {
        'a': os.path.join(tmpdir, 'a_stock.db'),
        'hk': os.path.join(tmpdir, 'hk_stock.db'),
        'us': os.path.join(tmpdir, 'us_stock.db'),
    }
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
    print(' StockQuantAssisant E2E 测试 — 以阿里巴巴为例')
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

    # 2.1 录入阿里巴巴
    resp = post('/api/stock/code', {'name': '阿里巴巴', 'hk': '09988', 'us': 'BABA'})
    body = resp.get_json()
    record(resp.status_code == 200 and body.get('success'),
           f'POST /api/stock/code (阿里巴巴) → {resp.status_code}')

    # 2.2 录入贵州茅台
    resp = post('/api/stock/code', {'name': '贵州茅台', 'a': '600519'})
    body = resp.get_json()
    record(resp.status_code == 200 and body.get('success'),
           f'POST /api/stock/code (贵州茅台) → {resp.status_code}')

    # 2.3 更新阿里巴巴（追加 us）
    resp = post('/api/stock/code', {'name': '阿里巴巴', 'us': 'BABA'})
    body = resp.get_json()
    record(resp.status_code == 200 and body.get('success'),
           f'POST /api/stock/code (阿里巴巴 更新) → {resp.status_code}')

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
    ok = resp.status_code == 200 and body.get('success') and body.get('count') >= 2
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

    # 3.2 重复注册（应返回已存在）
    resp = post('/api/stock/register', {'stock': '阿里巴巴'})
    body = resp.get_json()
    ok = resp.status_code == 200 and '已存在' in body.get('message', '')
    record(ok, f'POST /api/stock/register (重复) → {body.get("message")}')

    # 3.3 注册 000001（A 股代码）
    resp = post('/api/stock/register', {'stock': '000001'})
    body = resp.get_json()
    ok = resp.status_code == 200 and '已创建' in body.get('message', '')
    record(ok, f'POST /api/stock/register (000001) → {body.get("message")}')

    # 3.4 注册 00700.HK（港股代码带后缀）
    resp = post('/api/stock/register', {'stock': '00700.HK'})
    body = resp.get_json()
    ok = resp.status_code == 200 and '已创建' in body.get('message', '')
    record(ok, f'POST /api/stock/register (00700.HK) → {body.get("message")}')

    # 3.5 注册 AAPL（美股代码）
    resp = post('/api/stock/register', {'stock': 'AAPL'})
    body = resp.get_json()
    mk = body.get('markets', [{}])
    ok = resp.status_code == 200 and '已创建' in body.get('message', '')
    record(ok, f'POST /api/stock/register (AAPL) → {body.get("message")}')

    # 3.6 缺少参数
    resp = post('/api/stock/register', {})
    record(resp.status_code == 400, f'POST /api/stock/register (缺参) → {resp.status_code}')

    # ─────────────────────────────────────────────
    print('\n📋 阶段 4: 工作流查询')
    # ─────────────────────────────────────────────

    # 4.1 按代码查询
    resp = get('/api/stock/09988/workflows')
    body = resp.get_json()
    ok = resp.status_code == 200 and len(body.get('workflows', [])) == 4
    record(ok, f'GET /api/stock/09988/workflows → {len(body.get("workflows", []))} workflows')

    # 4.2 查询 BABA
    resp = get('/api/stock/BABA/workflows')
    body = resp.get_json()
    ok = resp.status_code == 200 and len(body.get('workflows', [])) == 4
    record(ok, f'GET /api/stock/BABA/workflows → {len(body.get("workflows", []))} workflows')

    # 4.3 查询所有工作流
    resp = get('/api/workflows')
    body = resp.get_json()
    total = body.get('count', 0)
    record(total >= 16, f'GET /api/workflows → count={total}')

    # ─────────────────────────────────────────────
    print('\n📋 阶段 5: 量化决策')
    # ─────────────────────────────────────────────

    # 5.1 阿里巴巴多市场决策（可能部分市场有数据、部分无）
    resp = post('/api/stock/decision', {'stock': '阿里巴巴'})
    body = resp.get_json()
    ok = resp.status_code == 200 and body.get('success') and body.get('count') == 2
    record(ok, f'POST /api/stock/decision (阿里巴巴) → {body.get("count")} markets')
    for r in body.get('results', []):
        if 'error' in r:
            RESULTS.append(f'      [{r["market"]}] {r["error"]}')
        else:
            RESULTS.append(f'      [{r["market"]}] pos={r["position"]}({r["position_label"]}) '
                           f'close={r["close"]} core_long={r["core_long"]} core_short={r["core_short"]}')

    # 5.2 000001 决策
    resp = post('/api/stock/decision', {'stock': '000001'})
    body = resp.get_json()
    ok = resp.status_code == 200 and body.get('success')
    record(ok, f'POST /api/stock/decision (000001) → {resp.status_code}')
    for r in body.get('results', []):
        if 'error' in r:
            RESULTS.append(f'      [{r["market"]}] {r["error"]}')
        else:
            RESULTS.append(f'      [{r["market"]}] pos={r["position"]}({r["position_label"]})')

    # 5.3 AAPL 决策
    resp = post('/api/stock/decision', {'stock': 'AAPL'})
    body = resp.get_json()
    ok = resp.status_code == 200 and body.get('success')
    record(ok, f'POST /api/stock/decision (AAPL) → {resp.status_code}')
    for r in body.get('results', []):
        if 'error' in r:
            RESULTS.append(f'      [{r["market"]}] {r["error"]}')
        else:
            RESULTS.append(f'      [{r["market"]}] pos={r["position"]}({r["position_label"]}) close={r["close"]}')

    # 5.4 不存在的名称
    resp = post('/api/stock/decision', {'stock': '不存在的股票'})
    record(resp.status_code == 400, f'POST /api/stock/decision (不存在) → {resp.status_code}')

    # 5.5 缺少参数
    resp = post('/api/stock/decision', {})
    record(resp.status_code == 400, f'POST /api/stock/decision (缺参) → {resp.status_code}')

    # 5.6 无效周期
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
    df = db_manager._get_metadata_conn().execute(
        "SELECT COUNT(*) FROM workflows"
    ).fetchone()
    wf_db_count = df[0]
    record(wf_db_count >= 15, f'metadata.db.workflows 行数 = {wf_db_count}')

    # 7.2 验证 stock_codes 表
    df = db_manager._get_metadata_conn().execute(
        "SELECT COUNT(*) FROM stock_codes"
    ).fetchone()
    sc_count = df[0]
    record(sc_count >= 2, f'metadata.db.stock_codes 行数 = {sc_count}')

    # 7.3 验证工作流恢复（模拟重启：创建新的 WorkflowService 实例，应加载相同数据）
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
