# 数据库表结构

所有数据库文件位于 `data/` 目录下，使用 [DuckDB](https://duckdb.org/) 存储。

## 概览

| 数据库文件 | 用途 | 表数量 |
|-----------|------|--------|
| `metadata.db` | 元数据（股票映射 + 工作流持久化） | 2 |
| `a_stock.db` | A 股行情数据 | N（每工作流 1 张） |
| `hk_stock.db` | 港股行情数据 | N |
| `us_stock.db` | 美股行情数据 | N |

---

## 1. metadata.db

### 1.1 stock_codes — 股票名称映射

录入股票中文名称与各市场代码的对应关系。

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `name` | TEXT | PRIMARY KEY | 股票中文名称（如 `阿里巴巴`） |
| `a_code` | TEXT | NULLABLE | A 股代码，6 位纯数字（如 `600519`） |
| `hk_code` | TEXT | NULLABLE | 港股代码，4-5 位数字（如 `09988`） |
| `us_code` | TEXT | NULLABLE | 美股代码，字母数字（如 `BABA`） |

**示例数据**：

| name | a_code | hk_code | us_code |
|------|--------|---------|---------|
| 阿里巴巴 | NULL | 09988 | BABA |
| 贵州茅台 | 600519 | NULL | NULL |
| 比亚迪 | 002594 | 01211 | NULL |

**创建 SQL**：

```sql
CREATE TABLE IF NOT EXISTS stock_codes (
    name TEXT PRIMARY KEY,
    a_code TEXT,
    hk_code TEXT,
    us_code TEXT
)
```

### 1.2 workflows — 工作流持久化

存储所有已注册的数据采集工作流，服务重启时自动加载恢复。

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | TEXT | PRIMARY KEY | 工作流唯一标识，格式 `{MARKET}_{CODE}_{INTERVAL}` |
| `market` | TEXT | NOT NULL | 市场代码：`a` / `hk` / `us` |
| `stock_code` | TEXT | NOT NULL | 内部股票代码，无后缀（如 `09988`） |
| `interval` | TEXT | NOT NULL | 周期：`daily` / `120min` / `90min` / `60min` |
| `table` | TEXT | NOT NULL | 对应数据表名，值与 `id` 相同 |
| `db_path` | TEXT | NOT NULL | 市场数据库文件路径（如 `/data/hk_stock.db`） |
| `created_at` | TEXT | NOT NULL | 创建时间（ISO 8601） |
| `active` | INTEGER | NOT NULL | 是否活跃：`1` / `0` |

**示例数据**：

| id | market | stock_code | interval | table | ... |
|----|--------|------------|----------|-------|-----|
| HK_09988.HK_daily | hk | 09988 | daily | HK_09988.HK_daily | ... |
| HK_09988.HK_60min | hk | 09988 | 60min | HK_09988.HK_60min | ... |
| US_BABA.US_daily | us | BABA | daily | US_BABA.US_daily | ... |

**创建 SQL**：

```sql
CREATE TABLE IF NOT EXISTS workflows (
    id TEXT PRIMARY KEY,
    market TEXT,
    stock_code TEXT,
    interval TEXT,
    "table" TEXT,
    db_path TEXT,
    created_at TEXT,
    active INTEGER
)
```

> 注：`table` 列名与 SQL 保留字冲突，使用双引号包裹。

---

## 2. 市场数据库（a_stock.db / hk_stock.db / us_stock.db）

每个市场数据库包含多张数据表，每张表对应一个工作流。

### 2.1 数据表（动态创建）

表名格式：`{MARKET}_{CODE}_{INTERVAL}`

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `timestamp` | TIMESTAMP | PRIMARY KEY | K 线时间戳 |
| `open` | DOUBLE | | 开盘价 |
| `high` | DOUBLE | | 最高价 |
| `low` | DOUBLE | | 最低价 |
| `close` | DOUBLE | | 收盘价 |
| `volume` | BIGINT | | 成交量 |
| `dividends` | DOUBLE | | 分红 |
| `stock_splits` | DOUBLE | | 拆股 |

**创建 SQL**：

```sql
CREATE TABLE IF NOT EXISTS "A_000001.SZ_daily" (
    timestamp TIMESTAMP PRIMARY KEY,
    open DOUBLE,
    high DOUBLE,
    low DOUBLE,
    close DOUBLE,
    volume BIGINT,
    dividends DOUBLE,
    stock_splits DOUBLE
)
```

> 注：表名含点号（`.`），创建和查询时使用双引号包裹。

**表名示例**：

| 数据库 | 表名 | 对应工作流 |
|--------|------|-----------|
| `a_stock.db` | `A_000001.SZ_daily` | A 股 000001 日线 |
| `a_stock.db` | `A_600519.SS_60min` | A 股 600519 60 分钟线 |
| `hk_stock.db` | `HK_09988.HK_daily` | 港股 09988 日线 |
| `us_stock.db` | `US_BABA.US_daily` | 美股 BABA 日线 |

## 3. 关系图

```
metadata.db
  ├─ stock_codes    ─── 名称 → 代码映射，供 detect_market 反查
  └─ workflows      ─── 工作流持久化，供 JobScheduler 恢复调度

a_stock.db
  ├─ A_000001.SZ_daily
  ├─ A_000001.SZ_120min
  ├─ A_000001.SZ_90min
  ├─ A_000001.SZ_60min
  └─ ...（其他 A 股）

hk_stock.db
  ├─ HK_09988.HK_daily
  ├─ HK_09988.HK_120min
  ├─ HK_09988.HK_90min
  ├─ HK_09988.HK_60min
  └─ ...

us_stock.db
  ├─ US_BABA.US_daily
  ├─ US_BABA.US_120min
  ├─ US_BABA.US_90min
  ├─ US_BABA.US_60min
  └─ ...
```
