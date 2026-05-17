# StockQuantAssisant 设计文档

## 1. 概述

StockQuantAssisant 是一个基于 Python + Flask 的股票数据采集、量化分析与任务调度系统，支持 A 股 / 港股 / 美股。数据以 **Parquet 列存格式** 存储在 **云对象存储 (S3 / OSS)** 上，通过 DuckDB 的 httpfs 扩展远程读写，实现 **存算分离** 和无状态部署。

## 2. 架构总览

```
┌──────────┐       ┌─────────────┐
│  run.py  │       │  调度层       │
│  Flask   │◄──────│  APScheduler │
└────┬─────┘       └──────┬──────┘
     │                    │
┌────▼────────────────────▼──────────┐
│           Service 层                │
│  workflow_service / stock_service   │
│  analysis_service / chart_service   │
│  resample                          │
└────┬───────────────┬───────────────┘
     │               │
┌────▼──────┐  ┌─────▼──────────────┐
│ Algos 层  │  │  Model 层           │
│ trend     │  │  DuckDB httpfs     │
│ structure │  │  + Parquet on OSS   │
│ sequence  │  └─────┬──────────────┘
│ decision  │        │
└───────────┘  ┌─────▼──────────────┐
               │ 外部存储 (S3 / OSS) │
               │ Parquet 列存文件     │
               └────────────────────┘
```

## 3. 模块设计

### 3.1 app/config.py — 全局配置

| 配置项 | 说明 |
|--------|------|
| `DATA_DIR` | 数据目录（默认 `~/.stockquant/data/`）；本地模式下 Parquet 存于此；OSS 模式下存于 S3 |
| `INTERVAL_MAP` | 采集层周期 → (period, interval) 映射；**仅包含 `5min`** |
| `INTERVAL_MINUTES` | 周期 → 分钟数（供 resample 和 scheduler 使用） |
| `RESAMPLE_INTERVALS` | 运行时合成支持的目标周期（供文档/调度引用） |
| `YFINANCE_TICKER_MAP` | 市场 → yfinance ticker 转换函数 |
| `TRADING_HOURS` | 各市场交易时段和时区 |
| OSS 配置 | `OSS_BUCKET` / `OSS_ENDPOINT` / `OSS_REGION` / `OSS_ACCESS_KEY_ID` / `OSS_ACCESS_KEY_SECRET` |

### 3.2 API 层 — app/api/routes.py

Flask Blueprint `api_bp`，挂载 `/api` 前缀。详见 [api.md](api.md)。

| 端点 | 方法 | 功能 |
|------|------|------|
| `/stock/code` | POST | 录入/更新股票名称→代码映射 |
| `/stock/codes` | GET | 查看所有映射 |
| `/stock/register` | POST | 注册股票数据工作流 |
| `/stock/decision` | POST | 查询量化决策结果 |
| `/stock/chart` | GET | 返回行情图表 PNG |
| `/stock/<code>/workflows` | GET | 查询指定股票工作流 |
| `/workflows` | GET | 查看所有工作流 |
| `/workflows/<id>` | DELETE | 删除工作流 |
| `/health` | GET | 健康检查 |

### 3.3 Service 层

#### stock_service.py

- `detect_market(input)` — 代码格式识别或名称反查 → `[(market, code), ...]`
- `resolve_stock_name(name)` — 从 `stock_codes` 表反查名称
- `fetch_stock_data(market, code, interval)` — 统一拉取 5min K 线（A/港股优先 akshare 回退 yfinance；美股 yfinance 5m）
- `collect_and_store(market, code, interval)` — 拉取 + 去重写入 Parquet；仅交易时段执行
- `is_trading_time(market)` — 交易时段判断

**数据源策略**：只采集 5min 一种粒度。60min / 90min / 120min / daily 由 `resample` 运行时合成，避免 Yahoo 不支持 120m、港股小时线为空、A 股小时线时区错配等问题。

#### workflow_service.py

`WorkflowService` 单例，采集层只保留 5min 工作流：

- `register_stock(input)` → `detect_market` → 为每个市场创建 1 个 5min 工作流
- `get_stock_workflows / get_all_workflows` → 查询
- `delete_workflow(wf_id)` → 从内存和 DB 中删除
- 工作流信息持久化到 `metadata/workflows.parquet`，启动时自动加载恢复

#### analysis_service.py

`analyze_stock(stock_input, interval='daily')`：
1. 解析输入 → 读 `*_5min` → `resample` 出日线 + 60/90/120
2. `DecisionEngine.summary_integrated(df_daily, intraday)`：趋势与序列只看日线，结构看 60/90/120 并合并
3. `_enrich_resonance_integrated`：统计 60/90/120 共振
4. 返回 `interval: integrated`

#### resample.py

`resample_ohlcv(df_5m, target_interval)`：按交易日分组、按 K 线序号切桶。聚合：`Open=first, High=max, Low=min, Close=last, Volume=sum`。桶内不足时输出尾巴 K 线。

#### chart_service.py

- `render_chart_png` — 单周期 K 线 + 趋势四轨
- `render_intraday_macd_png` — K 线 + MACD 副图（60/90/120 结构可视化）
- `render_integrated_dashboard_png` — 纵向拼接日线趋势 + 三周期 MACD

### 3.4 Algos 层 — 量化算法

位于 `app/algos/`，四个模块对应 [algorithm.md](algorithm.md) 的四级体系。

#### trend.py — 趋势量化

`TrendChannel(short_period=26, long_period=90, offset_pct=0.03)`

通道公式：`EMA(RollingMax(High, N), N) × (1+offset)` / `EMA(RollingMin(Low, N), N) × (1−offset)`

仓位：满仓(10.0) / 重仓(6.0) / 轻仓(4.0) / 空仓(0.0)，信号执行时点 `T+1 Open`。

#### structure.py — 结构量化

`MACDStructure(fast=12, slow=26, signal=9, smooth_k=2, eps=0.001, effective_horizon=5)`

状态机：`normal → top_divergence → top_75 → top_100 → reset → normal`（底部对称）。关键修复：peak_dif 逐根更新、100% 后立即 reset、带符号相对阈值比较、75% 需连续 K=2 根确认。

多周期共振只在 60/90/120min 上统计，`resonance.level` 为 1.0 / 1.5 / 2.0。

#### sequence.py — 序列量化

`NineSequence(effective_horizon=5)`：高九（连续 9 根 `Close[i] > Close[i-4]`）、低九（对称）。有效期内价格突破 9 区间极值则立即失效，超 `H=5` 根自动失效。仅做 Setup 9，不做 Countdown 13。

#### decision.py — 决策引擎

`DecisionEngine` 三级优先级：

| 级别 | 模块 | 职责 |
|------|------|------|
| 第一级 | TrendChannel | 仓位跃迁 → 主 BS 点 |
| 第二级 | MACDStructure（3 周期并行 + 共振） | 修饰权重，升级 confidence = core |
| 第三级 | NineSequence | 与结构共振时增强 weight，升级 confidence = resonance |

核心规则：`position ≥ 6` 不做空、`position ≤ 4` 不做多，避免仓位 4/6 同时触发的矛盾。

`summary_integrated(df_daily, intraday)` 返回：`decision`（action/weight/confidence/execute_at）、`signals`（structure/sequence/resonance）、`standards`（trend 四轨 + structure 阈值）、`view`（人话态势 + 触发价位）。

### 3.5 Model 层 — app/models/database.py

`DatabaseManager` 基于 DuckDB 内存引擎 + httpfs 扩展，实现 Parquet on OSS 存算分离：

- **OHLCV 数据**：每个 stock/market 一个 Parquet 文件，路径 `{market}/{table_name}.parquet`
- **元数据**（stock_codes / workflows）：存储于 `metadata/` 目录下 Parquet 文件，启动时加载到 DuckDB 内存表，写操作实时刷新
- 方法：`table_exists` / `insert_data` / `get_data` / `upsert_stock_code` / `save_workflow` / `load_workflows` 等

### 3.6 调度层 — app/scheduler/job_scheduler.py

`JobScheduler` 基于 APScheduler `BackgroundScheduler`，按 `INTERVAL_MINUTES` 创建 `IntervalTrigger`，非交易时段自动跳过。

### 3.7 部署 — Parquet on OSS

#### 存储结构

```
s3://{bucket}/
├── metadata/
│   ├── stock_codes.parquet
│   └── workflows.parquet
├── a/
│   ├── A_600519.SS_5min.parquet
│   └── A_000001.SZ_5min.parquet
├── hk/
│   └── HK_09988.HK_5min.parquet
└── us/
    └── US_BABA.US_5min.parquet
```

采集层只保留 5min；高粒度由 resample 运行时合成。

#### 读写流程

```
采集: fetch → DataFrame → merge → COPY TO 's3://...' (Parquet)
分析: read_parquet('s3://...') → DuckDB 谓词下推/列裁剪 → DataFrame → algo
```

#### 环境变量

| 变量 | 说明 |
|------|------|
| `OSS_BUCKET` | Bucket 名称，不设使用本地 Parquet |
| `OSS_ENDPOINT` | S3 兼容 Endpoint |
| `OSS_REGION` | 区域（默认 `us-east-1`） |
| `OSS_ACCESS_KEY_ID` / `OSS_ACCESS_KEY_SECRET` | 不设使用 IAM 角色 |
| `STOCKQUANT_DATA_DIR` | 本地数据目录 |

#### 认证

- IAM 角色：不设 AK/SK，DuckDB 从云平台自动获取
- 手动 AK/SK：设置 `OSS_ACCESS_KEY_ID` + `OSS_ACCESS_KEY_SECRET`

## 4. 数据流

```
POST /api/stock/register {"stock": "阿里巴巴"}
  ├─ detect_market("阿里巴巴") → resolve_stock_name → [('hk','09988'), ('us','BABA')]
  ├─ _register_one_market('hk', '09988')
  │   ├─ collect_and_store(interval='5min') → akshare → Parquet
  │   └─ save_workflow → metadata/workflows.parquet
  ├─ _register_one_market('us', 'BABA') → yfinance 5m → Parquet
  └─ 返回 2 个工作流 ID

POST /api/stock/decision {"stock": "阿里巴巴", "interval": "daily"}
  ├─ detect_market → [('hk','09988'), ('us','BABA')]
  ├─ get_data → 5min DataFrame → resample → daily + 60/90/120
  │   └─ DecisionEngine.summary_integrated → {action, weight, confidence, ...}
  └─ 返回两个市场决策结果（interval: integrated）
```

## 5. 关键技术决策

| 决策 | 理由 |
|------|------|
| DuckDB + Parquet on OSS (存算分离) | Parquet 列存直存 OSS，httpfs 远程查询，零本地盘 |
| akshare + yfinance 双数据源 | akshare 对 A 股支持好（前复权），yfinance 覆盖港股美股 |
| 仅采集 5min，高粒度运行时合成 | 规避 Yahoo 不支持 120m、港股小时线为空、A 股时区错配 |
| DIF 带符号相对阈值比较 | 统一顶/底背离判定，解决负 DIF 和 |DIF|<1 的语义反转 |
| 结构状态机 100% 后立即 reset | 避免单股生命周期只产一次信号 |
| 钝化区间 DIF 极值逐根更新 | 修复 DIF 在两峰之间漏检 |
| 趋势通道 EMA(RollingMax(High,N), N) | 与多空通道原意一致；直接 EMA(High) 退化为普通均线 |
| 仓位跃迁作主 BS，结构/序列作权重 | BS 点可量化、可下单；区分 trend/core/resonance 三档置信度 |
| 决策阈值 `≥ 6` / `≤ 4` | 修正历史阈值在仓位 4/6 时的逻辑矛盾 |
| 信号 T+1 开盘撮合 | 趋势用 T 日收盘判定，避免未来函数 |

## 6. 项目结构

```
StockQuantAssisant/
├── run.py
├── requirements.txt
├── pyproject.toml
├── docs/
│   ├── api.md
│   ├── server.md
│   ├── algorithm.md
│   ├── design.md
│   └── db_table.md
├── app/
│   ├── __init__.py
│   ├── config.py
│   ├── algos/
│   │   ├── trend.py
│   │   ├── structure.py
│   │   ├── sequence.py
│   │   └── decision.py
│   ├── api/
│   │   └── routes.py
│   ├── models/
│   │   └── database.py
│   ├── scheduler/
│   │   └── job_scheduler.py
│   └── services/
│       ├── stock_service.py
│       ├── workflow_service.py
│       ├── analysis_service.py
│       ├── chart_service.py
│       └── resample.py
├── tests/
│   ├── conftest.py
│   ├── test_algorithm.py
│   ├── test_analysis_service.py
│   ├── test_api.py
│   ├── test_chart.py
│   ├── test_database.py
│   ├── test_integration.py
│   ├── test_parquet_store.py
│   ├── test_resample.py
│   ├── test_stock_service.py
│   └── test_workflow_service.py
└── e2e/
    ├── run.py
    └── test_parquet.py
```

## 7. 测试

基于 pytest，共 212 个测试函数覆盖：股票识别、Parquet CRUD、工作流管理、API 端点、三个量化算法、决策引擎、多周期合成、集成流程。

```bash
pytest tests/ -v                        # 单元测试
python3 e2e/test_parquet.py             # Parquet 本地 E2E
python3 e2e/test_parquet.py --minio     # Parquet on OSS E2E
```
