# StockQuantAssisant - 股票量化助手

基于 Python + Flask 的股票数据采集、量化分析与调度服务，支持 A 股/港股/美股的多周期历史数据自动同步与量化决策输出。

## 项目结构

```
StockQuantAssisant/
├── run.py                         # 启动入口
├── requirements.txt               # 依赖
├── docs/
│   ├── api.md                     # API 文档
│   ├── server.md                  # 服务端需求文档
│   ├── algorithm.md               # 量化算法文档
│   ├── design.md                  # 系统设计文档
│   └── db_table.md                # 数据库表结构文档
├── app/
│   ├── __init__.py                # Flask 工厂函数
│   ├── config.py                  # 配置文件
│   ├── algos/
│   │   ├── trend.py               # 趋势量化（双均线通道）
│   │   ├── structure.py           # 结构量化（MACD 背离判定）
│   │   ├── sequence.py            # 序列量化（九转序列）
│   │   └── decision.py            # 决策引擎（三级整合）
│   ├── api/
│   │   └── routes.py              # REST API 路由
│   ├── models/
│   │   └── database.py            # DuckDB 数据库管理（股票数据 + 元数据）
│   ├── scheduler/
│   │   └── job_scheduler.py       # APScheduler 任务调度
│   └── services/
│       ├── stock_service.py       # 股票识别、数据拉取（akshare/yfinance）
│       ├── workflow_service.py    # 工作流注册与管理
│       └── analysis_service.py    # 量化分析服务
├── data/                          # DuckDB 数据库文件（gitignore）
└── tests/                         # 测试用例（123 个）
    ├── conftest.py
    ├── test_stock_service.py
    ├── test_database.py
    ├── test_workflow_service.py
    ├── test_api.py
    ├── test_integration.py
    └── test_algorithm.py
```

## 快速开始

### 安装依赖

```bash
pip install -r requirements.txt
```

### 启动服务

```bash
python run.py --host 0.0.0.0 --port 5000
```

可选参数：
- `--host` : 监听地址（默认 `0.0.0.0`）
- `--port` : 监听端口（默认 `5000`）
- `--debug` : 开启调试模式

### 运行测试

```bash
pytest tests/ -v
```

## 主要功能

### 数据采集与调度

- 支持 A 股 / 港股 / 美股三市场，代码或名称输入
- 名称自动匹配多市场（如"阿里巴巴"→ 港股 09988.HK + 美股 BABA.US）
- 每个市场注册 4 个周期工作流（daily / 120min / 90min / 60min）
- 初次注册拉取约 200 周期历史数据，之后定时增量更新
- 工作流持久化，服务重启自动恢复（存于 metadata.db）

### 量化决策引擎

- **趋势量化**：双 EMA 通道（短周期 25 / 长周期 90）判断趋势方向，输出 10/6/4/0 目标仓位
- **结构量化**：MACD 背离检测（钝化 → 75% DIF 转向 → 100% DIF/DEA 交叉），量化趋势衰竭转折点
- **序列量化**：九转序列（高九卖出 / 低九买入），左侧择时信号
- **决策整合**：三级优先级 — 趋势定仓 → 结构择时 → 序列共振

## REST API

详见 [docs/api.md](docs/api.md)

核心端点：

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/stock/code` | 录入股票名称 → 市场代码映射 |
| `GET` | `/api/stock/codes` | 查看所有已录入映射 |
| `POST` | `/api/stock/register` | 注册股票数据工作流 |
| `POST` | `/api/stock/decision` | 查询量化决策结果 |
| `GET` | `/api/workflows` | 查看所有工作流 |
| `GET` | `/api/stock/<code>/workflows` | 查看指定股票工作流 |
| `DELETE` | `/api/workflows/<id>` | 删除工作流 |
| `GET` | `/api/health` | 健康检查 |

## 工作流机制

- **唯一标识**：`{市场}_{股票代码}_{周期}`（如 `A_000001.SZ_daily`）
- **市场代码**：`A`（A 股）、`HK`（港股）、`US`（美股）
- **周期**：`daily`、`120min`、`90min`、`60min`

注册新股票时，工作流会拉取约 200 个完整周期的历史数据写入 DuckDB，之后按各自周期定时增量更新，仅在交易时段执行。

## 数据库

- **市场数据**：`a_stock.db` / `hk_stock.db` / `us_stock.db` — 每工作流一张表，表名 = 工作流 ID
- **元数据**：`metadata.db` 包含两张表：
  - `stock_codes` — 股票名称 → A 股/港股/美股代码映射
  - `workflows` — 工作流持久化（id + JSON data）
- 表结构：`timestamp`、`open`、`high`、`low`、`close`、`volume`、`dividends`、`stock_splits`

## 数据源

- A 股：[akshare](https://github.com/akfamily/akshare)（不可用时自动回退 yfinance）
- 港股 / 美股：[yfinance](https://github.com/ranaroussi/yfinance)

## 技术栈

| 组件 | 技术 |
|------|------|
| Web 框架 | Flask |
| 数据库 | DuckDB |
| 数据处理 | Pandas / NumPy |
| 任务调度 | APScheduler |
| A 股数据 | akshare |
| 港股/美股数据 | yfinance |
| 测试 | pytest |
