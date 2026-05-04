#!/usr/bin/env python3
"""
E2E 测试脚本 — OSS 状态持久化全链路验证

验证: 服务停止时将 DuckDB 文件上传 OSS，新实例启动时下载恢复，
      多次生命周期间数据完整一致。

用法:
    # 使用 moto 模拟 S3（默认，无需外部服务，无需网络）
    python3 e2e/test_oss.py

    # 使用 MinIO 真服务器
    export OSS_BUCKET=test-bucket
    export OSS_ENDPOINT=http://localhost:9000
    export OSS_ACCESS_KEY_ID=minioadmin
    export OSS_ACCESS_KEY_SECRET=minioadmin
    python3 e2e/test_oss.py --minio

MinIO 快速启动:
    docker run -d --name minio-test -p 9000:9000 -p 9001:9001 \
      -e MINIO_ROOT_USER=minioadmin -e MINIO_ROOT_PASSWORD=minioadmin \
      quay.io/minio/minio server /data --console-address :9001
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


def _reset_app_state(data_dir):
    import app.config as app_config
    import app.services.oss_sync as oss_mod
    import app.models.database as db_mod

    app_config.Config.DATA_DIR = data_dir
    app_config.Config.METADATA_DB_PATH = os.path.join(data_dir, 'metadata.db')
    app_config.Config.DB_PATHS = {
        'a': os.path.join(data_dir, 'a_stock.db'),
        'hk': os.path.join(data_dir, 'hk_stock.db'),
        'us': os.path.join(data_dir, 'us_stock.db'),
    }

    oss_mod._ENABLED = None
    oss_mod._CLIENT = None
    db_mod.db_manager._connections.clear()


def _create_test_data(data_dir):
    """直接写入 DuckDB 文件，模拟服务运行后产生的数据"""
    import duckdb

    # metadata.db
    meta_path = os.path.join(data_dir, 'metadata.db')
    meta_conn = duckdb.connect(meta_path)
    meta_conn.execute("""
        CREATE TABLE IF NOT EXISTS stock_codes (
            name TEXT PRIMARY KEY, a_code TEXT, hk_code TEXT, us_code TEXT
        )
    """)
    meta_conn.execute("""
        CREATE TABLE IF NOT EXISTS workflows (
            id TEXT PRIMARY KEY, market TEXT, stock_code TEXT,
            interval TEXT, "table" TEXT, db_path TEXT,
            created_at TEXT, active INTEGER
        )
    """)
    meta_conn.execute("INSERT INTO stock_codes VALUES ('贵州茅台', '600519', NULL, NULL)")
    meta_conn.execute("INSERT INTO stock_codes VALUES ('苹果', NULL, NULL, 'AAPL')")
    meta_conn.execute("INSERT INTO stock_codes VALUES ('腾讯', NULL, '00700', NULL)")
    meta_conn.execute(
        "INSERT INTO workflows VALUES "
        "('A_600519_daily', 'a', '600519', 'daily', 'A_600519.SZ_daily', "
        "'a_stock.db', '2024-01-01T09:00:00', 1)"
    )
    meta_conn.close()

    # a_stock.db — 包含一条 workflow 表
    a_path = os.path.join(data_dir, 'a_stock.db')
    a_conn = duckdb.connect(a_path)
    a_conn.execute("""
        CREATE TABLE IF NOT EXISTS "A_600519.SZ_daily" (
            timestamp TIMESTAMP PRIMARY KEY, open DOUBLE, high DOUBLE,
            low DOUBLE, close DOUBLE, volume BIGINT,
            dividends DOUBLE, stock_splits DOUBLE
        )
    """)
    a_conn.execute(
        "INSERT INTO \"A_600519.SZ_daily\" VALUES "
        "('2024-01-02 00:00:00', 1800.0, 1820.0, 1790.0, 1810.0, 10000000, 0.0, 0.0)"
    )
    a_conn.close()

    # hk_stock.db / us_stock.db — 空文件（无相关表）
    for fname in ('hk_stock.db', 'us_stock.db'):
        duckdb.connect(os.path.join(data_dir, fname)).close()


def _checksums(data_dir):
    checksums = {}
    for root, _dirs, files in os.walk(data_dir):
        for fname in sorted(files):
            if fname.endswith('.db'):
                path = os.path.join(root, fname)
                with open(path, 'rb') as f:
                    checksums[os.path.relpath(path, data_dir)] = hashlib.sha256(f.read()).hexdigest()
    return checksums


def _verify_roundtrip(src_dir, dst_dir, label):
    src_sums = _checksums(src_dir)
    dst_sums = _checksums(dst_dir)

    record(len(src_sums) > 0, f'{label} 源目录有 {len(src_sums)} 个 DB 文件')
    record(src_sums.keys() == dst_sums.keys(),
           f'{label} 目录结构一致: {sorted(src_sums.keys())}')

    for fname, src_hash in src_sums.items():
        dst_hash = dst_sums.get(fname)
        record(src_hash == dst_hash, f'{label} SHA256 一致: {fname}')

    # DB 内容可读性验证（至少能打开并查询）
    import duckdb
    meta = duckdb.connect(os.path.join(dst_dir, 'metadata.db'))
    codes = meta.execute("SELECT name FROM stock_codes ORDER BY name").fetchall()
    record(len(codes) > 0, f'{label} stock_codes 表可读，行数: {len(codes)}')
    meta.close()


def run():
    global PASS, FAIL
    args = parse_args()

    print('=' * 60)
    backend = 'MinIO' if args.minio else 'moto (S3 mock)'
    print(f' StockQuantAssisant OSS E2E 测试 — {backend}')
    print('=' * 60)

    # --- 环境准备 ---
    if args.minio:
        required = ['OSS_BUCKET', 'OSS_ENDPOINT', 'OSS_ACCESS_KEY_ID', 'OSS_ACCESS_KEY_SECRET']
        missing = [k for k in required if not os.environ.get(k)]
        if missing:
            print(f'❌ MinIO 缺少环境变量: {", ".join(missing)}')
            return False
        import boto3
        s3 = boto3.client(
            's3',
            endpoint_url=os.environ['OSS_ENDPOINT'],
            aws_access_key_id=os.environ['OSS_ACCESS_KEY_ID'],
            aws_secret_access_key=os.environ['OSS_ACCESS_KEY_SECRET'],
            region_name=os.environ.get('OSS_REGION', 'us-east-1'),
        )
        bucket = os.environ['OSS_BUCKET']
        try:
            s3.head_bucket(Bucket=bucket)
        except Exception:
            s3.create_bucket(Bucket=bucket)
            print(f'📦 创建 Bucket: {bucket}')
    else:
        import boto3
        from moto import mock_aws
        mock_aws().start()
        os.environ['OSS_BUCKET'] = 'test-bucket'
        os.environ['OSS_REGION'] = 'us-east-1'
        s3 = boto3.client('s3', region_name='us-east-1')
        try:
            s3.create_bucket(Bucket='test-bucket')
        except Exception:
            pass

    from app.services.oss_sync import sync_down, sync_up

    # ================================================
    print('\n📋 阶段 1: 模拟初次注册 → 上传 OSS')
    # ================================================
    tmp1 = tempfile.mkdtemp(prefix='oss_e2e_1_')
    _reset_app_state(tmp1)
    sync_down(tmp1)
    _create_test_data(tmp1)
    sync_up(tmp1)
    record(True, '数据已上传到 OSS')

    # ================================================
    print('\n📋 阶段 2: 模拟新实例启动 → 下载验证')
    # ================================================
    tmp2 = tempfile.mkdtemp(prefix='oss_e2e_2_')
    _reset_app_state(tmp2)
    sync_down(tmp2)
    _verify_roundtrip(tmp1, tmp2, '阶段2')

    # ================================================
    print('\n📋 阶段 3: 增量数据 + 再次同步 → 再次恢复')
    # ================================================
    import duckdb

    # 在 tmp1 新增数据（模拟新一天的数据采集）
    a_conn = duckdb.connect(os.path.join(tmp1, 'a_stock.db'))
    a_conn.execute(
        "INSERT INTO \"A_600519.SZ_daily\" VALUES "
        "('2024-01-03 00:00:00', 1815.0, 1830.0, 1805.0, 1825.0, 12000000, 0.0, 0.0)"
    )
    a_conn.close()

    meta_conn = duckdb.connect(os.path.join(tmp1, 'metadata.db'))
    meta_conn.execute("INSERT INTO stock_codes VALUES ('比亚迪', '002594', NULL, NULL)")
    meta_conn.execute(
        "INSERT INTO workflows VALUES "
        "('A_002594_daily', 'a', '002594', 'daily', 'A_002594.SZ_daily', "
        "'a_stock.db', '2024-01-02T09:00:00', 1)"
    )
    meta_conn.close()

    _reset_app_state(tmp1)
    sync_up(tmp1)
    record(True, '增量数据已上传')

    # 新实例验证
    tmp3 = tempfile.mkdtemp(prefix='oss_e2e_3_')
    _reset_app_state(tmp3)
    sync_down(tmp3)
    _verify_roundtrip(tmp1, tmp3, '阶段3')

    # 验证增量行数
    a_conn = duckdb.connect(os.path.join(tmp3, 'a_stock.db'))
    row_count = a_conn.execute(
        "SELECT COUNT(*) FROM \"A_600519.SZ_daily\""
    ).fetchone()[0]
    a_conn.close()
    record(row_count == 2, f'阶段3 OHLCV 行数: {row_count} (预期 2)')

    # 验证新增 stock_code
    meta_conn = duckdb.connect(os.path.join(tmp3, 'metadata.db'))
    codes = meta_conn.execute("SELECT name FROM stock_codes ORDER BY name").fetchall()
    meta_conn.close()
    record(len(codes) == 4, f'阶段3 stock_codes 数量: {len(codes)} (预期 4)')

    # --- 清理 ---
    if not args.minio:
        from moto import mock_aws
        try:
            mock_aws().stop()
        except Exception:
            pass

    # --- 结果 ---
    print(f'\n{"=" * 60}')
    print(f' 结果: {PASS} 通过 / {FAIL} 失败 / {PASS + FAIL} 总计')
    print(f'{"=" * 60}')
    for r in RESULTS:
        print(r)

    return FAIL == 0


def parse_args():
    parser = argparse.ArgumentParser(description='OSS 状态持久化 E2E 测试')
    parser.add_argument('--minio', action='store_true',
                        help='使用 MinIO (需设置 OSS_* 环境变量)')
    return parser.parse_args()


if __name__ == '__main__':
    sys.exit(0 if run() else 1)
