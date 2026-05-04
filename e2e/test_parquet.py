#!/usr/bin/env python3
"""
E2E 测试脚本 — Parquet on OSS 存算分离全链路验证

验证: 服务直接读写 OSS 上的 Parquet 文件，零本地持久化。
      DuckDB httpfs 扩展负责 S3 通信，无需 boto3。

用法:
    # 本地模式（无需 OSS，直接验证 Parquet 存储逻辑）
    python3 e2e/test_parquet.py

    # MinIO 模式（需要启动 MinIO 并创建 bucket）
    export OSS_BUCKET=test-bucket
    export OSS_ENDPOINT=http://localhost:9000
    export OSS_ACCESS_KEY_ID=minioadmin
    export OSS_ACCESS_KEY_SECRET=minioadmin
    python3 e2e/test_parquet.py --minio
"""

import argparse
import hashlib
import logging
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

PASS = 0
FAIL = 0
RESULTS = []


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


def _reset_app_state(data_dir, oss_bucket=None):
    import app.config as app_config
    import app.models.database as db_mod

    app_config.Config.DATA_DIR = data_dir
    app_config.Config.OSS_BUCKET = oss_bucket

    db_mod.db_manager.close_all()
    db_mod.db_manager.__init__()


def _create_test_data(db_mgr):
    import pandas as pd

    # metadata
    db_mgr.upsert_stock_code('贵州茅台', a_code='600519')
    db_mgr.upsert_stock_code('苹果', us_code='AAPL')

    db_mgr.save_workflow('A_600519_daily', {
        'market': 'a', 'stock_code': '600519', 'interval': 'daily',
        'table': 'A_600519_daily', 'db_path': '', 'created_at': '2024-01-01', 'active': True,
    })

    # OHLCV data
    dates = pd.date_range('2024-01-01', periods=30, freq='B')
    df = pd.DataFrame({
        'Open': [1800.0 + i * 0.5 for i in range(30)],
        'High': [1820.0 + i * 0.5 for i in range(30)],
        'Low': [1790.0 + i * 0.5 for i in range(30)],
        'Close': [1810.0 + i * 0.5 for i in range(30)],
        'Volume': [10000000] * 30,
        'Dividends': [0.0] * 30,
        'Stock Splits': [0.0] * 30,
    }, index=dates)
    df.index.name = 'timestamp'
    db_mgr.insert_data('a', 'A_600519_daily', df)


def _verify_data(db_mgr):
    from app.models.database import DatabaseManager

    codes = db_mgr.get_all_stock_codes()
    record(len(codes) >= 2, f'stock_codes 数量: {len(codes)}')

    wfs = db_mgr.load_workflows()
    record('A_600519_daily' in wfs, 'workflow A_600519_daily 存在')

    df = db_mgr.get_data('a', 'A_600519_daily')
    record(len(df) == 30, f'OHLCV 行数: {len(df)} (预期 30)')

    assert 'timestamp' in df.columns
    assert 'close' in df.columns or 'Close' in df.columns


def run():
    global PASS, FAIL
    args = parse_args()

    print('=' * 60)
    bg = 'MinIO (真实 S3)' if args.minio else 'Local Parquet'
    print(f' StockQuantAssisant Parquet E2E 测试 — {bg}')
    print('=' * 60)

    from app.models.database import DatabaseManager

    # --- MinIO 模式: 创建 bucket ---
    if args.minio:
        required = ['OSS_BUCKET', 'OSS_ENDPOINT', 'OSS_ACCESS_KEY_ID', 'OSS_ACCESS_KEY_SECRET']
        missing = [k for k in required if not os.environ.get(k)]
        if missing:
            print(f'❌ 缺少环境变量: {", ".join(missing)}')
            return False
        import boto3
        s3 = boto3.client(
            's3',
            endpoint_url=os.environ['OSS_ENDPOINT'],
            aws_access_key_id=os.environ['OSS_ACCESS_KEY_ID'],
            aws_secret_access_key=os.environ['OSS_ACCESS_KEY_SECRET'],
            region_name=os.environ.get('OSS_REGION', 'us-east-1'),
        )
        try:
            s3.head_bucket(Bucket=os.environ['OSS_BUCKET'])
        except Exception:
            s3.create_bucket(Bucket=os.environ['OSS_BUCKET'])

    # ================================================
    print('\n📋 阶段 1: 创建数据 → 写入 Parquet')
    # ================================================
    tmp1 = tempfile.mkdtemp(prefix='pq_e2e_1_')
    oss_bucket = os.environ.get('OSS_BUCKET') if args.minio else None
    _reset_app_state(tmp1, oss_bucket)

    db1 = DatabaseManager()
    _create_test_data(db1)
    db1.close_all()
    record(True, '阶段1: 数据已写入 Parquet')

    # ================================================
    print('\n📋 阶段 2: 新实例 → 读取 Parquet')
    # ================================================
    if not args.minio:
        tmp2 = tmp1  # Same dir for local mode
    else:
        tmp2 = tempfile.mkdtemp(prefix='pq_e2e_2_')
    _reset_app_state(tmp2, oss_bucket)

    db2 = DatabaseManager()
    _verify_data(db2)
    db2.close_all()

    # ================================================
    print('\n📋 阶段 3: 增量追加 → 再次读取')
    # ================================================
    _reset_app_state(tmp2, oss_bucket)
    db3 = DatabaseManager()

    import pandas as pd
    new_dates = pd.date_range('2024-03-01', periods=5, freq='B')
    df_new = pd.DataFrame({
        'Open': [1815.0] * 5, 'High': [1830.0] * 5,
        'Low': [1805.0] * 5, 'Close': [1820.0] * 5,
        'Volume': [11000000] * 5, 'Dividends': [0.0] * 5, 'Stock Splits': [0.0] * 5,
    }, index=new_dates)
    df_new.index.name = 'timestamp'
    inserted = db3.insert_data('a', 'A_600519_daily', df_new)

    db3.upsert_stock_code('腾讯', hk_code='00700')
    db3.close_all()

    record(inserted == 5, f'阶段3 新增 {inserted} 行 (预期 5)')

    # 新实例验证
    if not args.minio:
        tmp3 = tmp2
    else:
        tmp3 = tempfile.mkdtemp(prefix='pq_e2e_3_')
    _reset_app_state(tmp3, oss_bucket)

    db4 = DatabaseManager()
    df_final = db4.get_data('a', 'A_600519_daily')
    record(len(df_final) == 35, f'阶段3 最终行数: {len(df_final)} (预期 35)')

    codes = db4.get_all_stock_codes()
    record(len(codes) == 3, f'阶段3 stock_codes 数量: {len(codes)} (预期 3)')
    db4.close_all()

    # ================================================
    # 结果
    # ================================================
    print(f'\n{"=" * 60}')
    print(f' 结果: {PASS} 通过 / {FAIL} 失败 / {PASS + FAIL} 总计')
    print(f'{"=" * 60}')
    for r in RESULTS:
        print(r)

    return FAIL == 0


def parse_args():
    p = argparse.ArgumentParser(description='Parquet on OSS E2E 测试')
    p.add_argument('--minio', action='store_true', help='MinIO 模式 (需设置 OSS_* 环境变量)')
    return p.parse_args()


if __name__ == '__main__':
    sys.exit(0 if run() else 1)
