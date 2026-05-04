# 数据存储结构

数据以 **Parquet 列存格式** 存储在云对象存储（S3 / 阿里云 OSS）上，由 [DuckDB](https://duckdb.org/) 的 httpfs 扩展直接远程读写。不配置 OSS 时，使用本地文件系统作为后备。

## 概览

| 存储路径 | 用途 | 文件数 |
|----------|------|--------|
| `metadata/stock_codes.parquet` | 股票名称映射 | 1 |
| `metadata/workflows.parquet` | 工作流持久化 | 1 |
| `{market}/{table_name}.parquet` | OHLCV 行情数据 | N（每工作流 1 个） |

**完整目录结构：**

```
s3://{bucket}/                         (OSS 模式)  或  {DATA_DIR}/  (本地模式)
├── metadata/
│   ├── stock_codes.parquet
│   └── workflows.parquet
├── a/
│   ├── A_000001.SZ_daily.parquet
│   ├── A_000001.SZ_120min.parquet
│   ├── A_000001.SZ_90min.parquet
│   ├── A_000001.SZ_60min.parquet
│   └── ...
├── hk/
│   ├── HK_09988.HK_daily.parquet
│   └── ...
└── us/
    ├── US_BABA.US_daily.parquet
    └── ...
```

## 1. metadata/stock_codes.parquet — 股票名称映射

录入股票中文名称与各市场代码的对应关系。

| 列名 | 类型 | 说明 |
|------|------|------|
| `name` | string | 股票中文名称（如 `阿里巴巴`） |
| `a_code` | string/nullable | A 股代码，6 位纯数字（如 `600519`） |
| `hk_code` | string/nullable | 港股代码，4-5 位数字（如 `09988`） |
| `us_code` | string/nullable | 美股代码，字母数字（如 `BABA`） |

## 2. metadata/workflows.parquet — 工作流持久化

存储所有已注册的数据采集工作流，服务重启时自动加载恢复。

| 列名 | 类型 | 说明 |
|------|------|------|
| `id` | string | 工作流唯一标识，格式 `{MARKET}_{CODE}_{INTERVAL}` |
| `market` | string | 市场代码：`a` / `hk` / `us` |
| `stock_code` | string | 内部股票代码，无后缀（如 `09988`） |
| `interval` | string | 周期：`daily` / `120min` / `90min` / `60min` |
| `table` | string | 对应 Parquet 文件名（不含扩展名），值与 `id` 相同 |
| `db_path` | string | 保留字段（当前为空字符串） |
| `created_at` | string | 创建时间（ISO 8601） |
| `active` | int | 是否活跃：`1` / `0` |

## 3. OHLCV 数据 Parquet 文件

文件路径：`{market}/{MARKET}_{CODE}_{INTERVAL}.parquet`

| 列名 | 类型 | 说明 |
|------|------|------|
| `timestamp` | timestamp | K 线时间戳 |
| `open` | float64 | 开盘价 |
| `high` | float64 | 最高价 |
| `low` | float64 | 最低价 |
| `close` | float64 | 收盘价 |
| `volume` | float64 | 成交量 |
| `dividends` | float64 | 分红 |
| `stock_splits` | float64 | 拆股 |

**文件示例：**

| 文件路径 | 对应工作流 |
|----------|-----------|
| `a/A_000001.SZ_daily.parquet` | A 股 000001 日线 |
| `a/A_600519.SS_60min.parquet` | A 股 600519 60 分钟线 |
| `hk/HK_09988.HK_daily.parquet` | 港股 09988 日线 |
| `us/US_BABA.US_daily.parquet` | 美股 BABA 日线 |

## 4. 读写机制

```
读:  DuckDB → read_parquet('s3://bucket/a/A_000001.SZ_daily.parquet')
     → 列裁剪 + 谓词下推 → 仅传输需要的行/列

写:  DuckDB → COPY (SELECT * FROM df) TO 's3://...' (FORMAT PARQUET)
     → 直接写 OSS，不经过本地磁盘
```

- **元数据**：启动时从 Parquet 加载到 DuckDB 内存表，写操作即时刷新到 OSS
- **OHLCV**：每次写入时读取已有数据 → 合并去重 → 写回 Parquet
- **本地模式**：不配 `OSS_BUCKET` 时自动使用本地文件路径，行为一致

## 5. 环境变量

| 变量 | 说明 |
|------|------|
| `OSS_BUCKET` | OSS Bucket 名称（不设则使用本地文件） |
| `OSS_ENDPOINT` | S3 兼容 Endpoint |
| `OSS_REGION` | 区域（默认 `us-east-1`） |
| `OSS_ACCESS_KEY_ID` | Access Key（不设使用 IAM 角色） |
| `OSS_ACCESS_KEY_SECRET` | Secret Key |
| `STOCKQUANT_DATA_DIR` | 本地数据目录（默认 `~/.stockquant/data/`） |
