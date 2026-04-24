# StockQuantAssisant 设计文档

## 1. 概述

StockQuantAssisant 是一个基于 Python + Flask 的股票数据采集、量化分析与任务调度系统，支持 A 股 / 港股 / 美股三个市场，提供多周期历史数据同步和量化交易信号输出。

## 2. 架构总览

```
┌─────────────────────────────────────────────────────┐
│                    run.py (入口)                      │
│  Flask app 创建 → APScheduler 启动 → HTTP 服务      │
└──────────┬─────────────────────┬────────────────────┘
           │                     │
    ┌──────▼──────┐       ┌──────▼──────────┐
    │  API 层      │       │  调度层          │
    │  routes.py   │◄──────│  job_scheduler   │
    │              │       │  (APScheduler)   │
    └──────┬───────┘       └──────┬───────────┘
           │                      │
    ┌──────▼──────────────────────▼───────────┐
    │              Service 层                  │
    │  ┌─────────────────────────────────┐    │
    │  │ workflow_service  (工作流管理)   │    │
    │  │ stock_service     (股票识别/采集)│    │
    │  │ analysis_service  (量化分析)     │    │
    │  └─────────────────────────────────┘    │
    └──────┬──────────────────┬───────────────┘
           │                  │
    ┌──────▼──────┐    ┌──────▼──────────┐
    │  Algos 层    │    │  Model 层        │
    │  trend       │    │  database.py     │
    │  structure   │    │  (DuckDB CRUD    │
    │  sequence    │    │   + 元数据管理)   │
    │  decision    │    │                  │
    └──────────────┘    └──────────────────┘
```

## 3. 模块设计

### 3.1 app/__init__.py — Flask 工厂

```python
def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    app.register_blueprint(api_bp, url_prefix='/api')
    return app
```

### 3.2 app/config.py — 全局配置

| 配置项 | 说明 |
|--------|------|
| `DATA_DIR` | `data/` 目录路径 |
| `METADATA_DB_PATH` | 元数据库路径 `data/metadata.db` |
| `DB_PATHS` | 三市场 DB 路径：`a_stock.db` / `hk_stock.db` / `us_stock.db` |
| `INTERVAL_MAP` | 周期 → yfinance(period, interval) 映射 |
| `INTERVAL_MINUTES` | 周期 → 调度间隔（分钟） |
| `YFINANCE_TICKER_MAP` | 市场 → yfinance ticker 转换函数 |
| `TRADING_HOURS` | 各市场交易时段和时区 |

### 3.3 API 层 — app/api/routes.py

使用 Flask Blueprint `api_bp`，挂载在 `/api` 前缀下。详见 [api.md](api.md)。

| 端点 | 方法 | 功能 |
|------|------|------|
| `/stock/code` | POST | 录入股票名称→代码映射 |
| `/stock/codes` | GET | 查看所有映射 |
| `/stock/register` | POST | 注册股票数据工作流 |
| `/stock/decision` | POST | 查询量化决策结果 |
| `/stock/<code>/workflows` | GET | 查询指定股票工作流 |
| `/workflows` | GET | 查看所有工作流 |
| `/workflows/<id>` | DELETE | 删除工作流 |
| `/health` | GET | 健康检查 |

### 3.4 Service 层

#### stock_service.py

核心函数：

| 函数 | 功能 |
|------|------|
| `detect_market(input)` | 代码格式识别或名称反查 → `[(market, code), ...]` |
| `format_stock_code(market, code)` | 内部代码 → 带后缀显示代码 |
| `get_workflow_id(market, code, interval)` | 构造工作流唯一标识 |
| `get_table_name(...)` | 别名，等于 `get_workflow_id(...)` |
| `fetch_stock_data(...)` | 拉取行情数据（A 股用 akshare，港股/美股用 yfinance） |
| `is_trading_time(market)` | 判断当前是否在交易时段 |
| `collect_and_store(...)` | 拉取 + 写入 DB（含去重） |
| `resolve_stock_name(name)` | 从 `stock_codes` 表反查名称 → `[(market, code), ...]` |

**数据源策略**：
- A 股：优先使用 [akshare](https://github.com/akfamily/akshare)（`stock_zh_a_hist`），不可用时回退 yfinance
- 港股 / 美股：使用 [yfinance](https://github.com/ranaroussi/yfinance)
- 仅在交易时段拉取数据，非交易时段跳过

#### workflow_service.py

`WorkflowService` 单例类：

- `register_stock(input)` → 调用 `detect_market` → 为每个识别的 (market, code) 创建 4 个工作流
- `check_existing_workflows_for_code(market, code)` → 检查是否已注册
- `_register_one_market(market, code)` → 创建表 + 拉取初始化数据 + 持久化
- `get_stock_workflows / get_all_workflows` → 查询
- `delete_workflow(wf_id)` → 从内存和 DB 中删除

**持久化**：工作流信息写入 `metadata.db` 的 `workflows` 表，服务启动时从 DB 自动加载恢复。

#### analysis_service.py

`analyze_stock(stock_input, interval='daily')`：
1. 调用 `detect_market` 解析输入
2. 对每个识别的 (market, code)，从 DB 读取历史数据
3. 运行 `DecisionEngine.evaluate()` 得到决策结果
4. 返回最新一条的决策摘要

### 3.5 Algos 层 — 量化算法

位于 `app/algos/`，四个模块对应 [algorithm.md](algorithm.md) 的四级算法体系。

#### trend.py — 趋势量化

`TrendChannel(short_period=25, long_period=90, offset_pct=0.03)`

- 短期通道上轨：EMA(rolling_max(High, 25), 25) × (1 + offset)
- 短期通道下轨：EMA(rolling_min(Low, 25), 25) × (1 - offset)
- 长期通道：同逻辑，周期 90

仓位规则：

| 条件 | 仓位 | 含义 |
|------|------|------|
| close > 短上轨 且 close > 长上轨 | 10.0 | 满仓 |
| close < 短下轨 且 close < 长下轨 | 0.0 | 空仓 |
| close < 短下轨 且 close > 长上轨 | 6.0 | 重仓（长期向上短期回调） |
| close > 短上轨 且 close < 长上轨 | 4.0 | 轻仓（短期反弹长期向下） |
| 其他 | 维持上一次 | 过渡状态 |

#### structure.py — 结构量化

`MACDStructure(fast=12, slow=26, signal=9)`

**状态机**：
```
正常 → [价格新高 + DIF 未新高] → 顶部背离 → [DIF 转向] → 75% 形成
                                                              ↓
                                                       [DIF 下穿 DEA] → 100% 完成
```

底部背离同理（价格新低 + DIF 未新低 → DIF 向上转 → DIF 上穿 DEA）。

**输出列**：
- `top_divergence` / `bottom_divergence`：背离进行中
- `top_structure_75` / `bottom_structure_75`：75% 形成
- `top_structure_100` / `bottom_structure_100`：100% 完成
- `top_structure_level` / `bottom_structure_level`：级别（持续周期数）

**DIF 取整**：`_round_dif(v) = int(abs(v) * 100)`，用于数值比较过滤噪声。

#### sequence.py — 序列量化

`NineSequence`

**高九**：连续 9 根 K 线 `Close[i] > Close[i-4]`，第 9 根时 `max(High[8], High[9]) > max(High[6], High[7])`

**低九**：连续 9 根 K 线 `Close[i] < Close[i-4]`，第 9 根时 `min(Low[8], Low[9]) < min(Low[6], Low[7])`

不满足条件时计数归零。信号仅在完整出现 "9" 时锁定。

#### decision.py — 决策引擎

`DecisionEngine` 组合上述三个模块，按三级优先级输出决策：

| 级别 | 模块 | 输出 |
|------|------|------|
| 第一级 | TrendChannel | `position` (10/6/4/0) |
| 第二级 | MACDStructure | `core_long` / `core_short` |
| 第三级 | NineSequence | `resonance_buy` / `resonance_sell` |

规则约束：
- `core_long`：仓位 ≥ 4 AND (底部75%或100%)
- `core_short`：仓位 ≤ 6 AND (顶部75%或100%)
- `resonance_buy`：core_long AND low9_signal
- `resonance_sell`：core_short AND high9_signal

### 3.6 Model 层 — app/models/database.py

`DatabaseManager` 管理所有 DuckDB 连接：

- **市场数据连接**：`get_connection(market)` → `a_stock.db` / `hk_stock.db` / `us_stock.db`
- **元数据连接**：`_get_metadata_conn()` → `metadata.db`

提供方法：
- 股票数据：`create_stock_table` / `insert_data` / `get_data` / `table_exists` / `get_latest_timestamp`
- 元数据：`upsert_stock_code` / `get_stock_codes` / `get_all_stock_codes` / `delete_stock_code`
- 工作流：`save_workflow` / `load_workflows` / `delete_workflow_by_id`
- 自动迁移：检测旧表结构并重建

详见 [db_table.md](db_table.md)。

### 3.7 调度层 — app/scheduler/job_scheduler.py

`JobScheduler` 基于 APScheduler 的 `BackgroundScheduler`：

- `add_workflow_job(wf_id, wf_data)` → 按 `interval` 对应的分钟数创建 `IntervalTrigger`
- `remove_workflow_job(wf_id)` → 移除定时任务
- `load_all_workflows()` → 从 `workflow_service.workflows` 加载所有活跃工作流
- 非业务时间自动跳过（`is_trading_time` 判断）

## 4. 数据流

```
POST /api/stock/register {"stock": "阿里巴巴"}
  │
  ├─ detect_market("阿里巴巴")
  │   └─ resolve_stock_name → stock_codes 表 → [('hk','09988'), ('us','BABA')]
  │
  ├─ _register_one_market('hk', '09988') ×4
  │   ├─ create_stock_table → hk_stock.db."HK_09988.HK_daily"
  │   ├─ collect_and_store → yfinance 拉取 → INSERT
  │   └─ save_workflow → metadata.db.workflows
  │
  ├─ _register_one_market('us', 'BABA') ×4
  │   └─ ... (同上)
  │
  └─ 返回 8 个工作流 ID

POST /api/stock/decision {"stock": "阿里巴巴"}
  │
  ├─ detect_market → [('hk','09988'), ('us','BABA')]
  │
  ├─ get_data(hk, 'HK_09988.HK_daily') → DataFrame
  │   └─ DecisionEngine.evaluate(df) → position, signals
  │
  ├─ get_data(us, 'US_BABA.US_daily') → DataFrame
  │   └─ DecisionEngine.evaluate(df) → position, signals
  │
  └─ 返回两个市场的决策结果
```

## 5. 关键技术决策

| 决策 | 理由 |
|------|------|
| DuckDB 单文件 DB，嵌套路径 | 嵌入式部署零配置，JSON → DuckDB 提升可靠性 |
| akShare + yfinance 双数据源 | akShare 对 A 股数据支持更好（前复权），yfinance 覆盖港股美股 |
| 交易时段过滤 | 避免非交易时段的无效 API 调用和数据噪声 |
| 工作流标识含点号（`.`） | 符合 server.md 规范，SQL 中以双引号包裹 |
| DIF 取整 `×100` | 单调保留比较顺序，避免小数值截断导致的假背离 |
| 三级决策整合 | 算法文档的层次化设计：趋势定仓位 → 结构定方向 → 序列精调入口 |
| 延迟加载 WorkflowService | 避免模块导入时 DB 未就绪的问题 |

## 6. 项目结构

```
StockQuantAssisant/
├── run.py
├── requirements.txt
├── docs/
│   ├── api.md
│   ├── server.md
│   ├── algorithm.md
│   ├── design.md              ← 本文档
│   └── db_table.md
├── app/
│   ├── __init__.py
│   ├── config.py
│   ├── algos/
│   │   ├── __init__.py
│   │   ├── trend.py
│   │   ├── structure.py
│   │   ├── sequence.py
│   │   └── decision.py
│   ├── api/
│   │   ├── __init__.py
│   │   └── routes.py
│   ├── models/
│   │   ├── __init__.py
│   │   └── database.py
│   ├── scheduler/
│   │   ├── __init__.py
│   │   └── job_scheduler.py
│   └── services/
│       ├── __init__.py
│       ├── stock_service.py
│       ├── workflow_service.py
│       └── analysis_service.py
├── data/                      # gitignore
└── tests/
    ├── conftest.py
    ├── test_algorithm.py
    ├── test_api.py
    ├── test_database.py
    ├── test_integration.py
    ├── test_stock_service.py
    └── test_workflow_service.py
```

## 7. 测试

基于 pytest，共 126 个测试用例，运行：

```bash
pytest tests/ -v
```

测试覆盖：股票识别、数据库 CRUD、工作流管理、API 端点、三个量化算法、决策引擎、集成流程。测试使用 `tempfile` 隔离数据库和文件系统。
