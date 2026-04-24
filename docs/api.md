# API 文档

Base URL: `/api`

所有响应均为 JSON 格式，包含 `success` 字段。

## 目录

- [健康检查](#健康检查)
- [股票代码映射](#股票代码映射)
- [工作流注册](#工作流注册)
- [量化决策](#量化决策)
- [工作流查询](#工作流查询)

---

## 健康检查

### GET /health

检查服务及调度器运行状态。

**响应** `200`
```json
{
  "status": "ok",
  "scheduler_running": true
}
```

---

## 股票代码映射

### POST /stock/code

录入或更新股票名称与各市场代码的映射关系。已存在的名称会更新对应市场代码，不影响未提供字段的原值。

**请求**
```json
{
  "name": "阿里巴巴",
  "a": "000001",
  "hk": "09988",
  "us": "BABA"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | string | 是 | 股票中文名称 |
| `a` | string | 否 | A 股代码（6 位纯数字） |
| `hk` | string | 否 | 港股代码（4-5 位纯数字） |
| `us` | string | 否 | 美股代码（字母和数字） |

> 至少提供 `a`、`hk`、`us` 中的一个。

**响应** `200`
```json
{ "success": true, "message": "股票映射 \"阿里巴巴\" 已保存" }
```

**响应** `400`
```json
{ "success": false, "message": "缺少 name 参数" }
```
```json
{ "success": false, "message": "至少需要提供 a、hk、us 中的一个市场代码" }
```

### GET /stock/codes

获取所有已录入的股票代码映射。

**响应** `200`
```json
{
  "success": true,
  "count": 3,
  "codes": [
    { "name": "阿里巴巴", "a_code": null, "hk_code": "09988", "us_code": "BABA" },
    { "name": "贵州茅台", "a_code": "600519", "hk_code": null, "us_code": null },
    { "name": "苹果", "a_code": null, "hk_code": null, "us_code": "AAPL" }
  ]
}
```

---

## 工作流注册

### POST /stock/register

根据股票代码或名称注册数据同步工作流。系统自动识别输入类型：

- **代码格式**：直接按格式匹配市场（如 `000001.SZ` → A 股，`00700.HK` → 港股，`AAPL` → 美股）
- **名称格式**：在 `stock_codes` 表中查找对应的市场代码，一个名称匹配多个市场时一次性注册所有市场

每个市场注册 4 个工作流（`daily` / `120min` / `90min` / `60min`），初次注册时拉取约 200 个周期的历史数据并按各自间隔定时增量更新。

**请求**
```json
{ "stock": "000001" }
```
```json
{ "stock": "阿里巴巴" }
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `stock` | string | 是 | 股票代码或名称 |

**响应** `200` — 新创建
```json
{
  "success": true,
  "message": "工作流已创建",
  "workflows": [
    "A_000001.SZ_daily",
    "A_000001.SZ_120min",
    "A_000001.SZ_90min",
    "A_000001.SZ_60min"
  ],
  "markets": [
    { "market": "a", "stock_code": "000001" }
  ]
}
```

**响应** `200` — 多市场（如输入 "阿里巴巴"，同时命中港股和美股）
```json
{
  "success": true,
  "message": "工作流已创建",
  "workflows": [
    "HK_09988.HK_daily",
    "HK_09988.HK_120min",
    "HK_09988.HK_90min",
    "HK_09988.HK_60min",
    "US_BABA.US_daily",
    "US_BABA.US_120min",
    "US_BABA.US_90min",
    "US_BABA.US_60min"
  ],
  "markets": [
    { "market": "hk", "stock_code": "09988" },
    { "market": "us", "stock_code": "BABA" }
  ]
}
```

**响应** `200` — 已存在
```json
{
  "success": true,
  "message": "工作流已存在",
  "workflows": ["A_000001.SZ_daily", "A_000001.SZ_120min", "A_000001.SZ_90min", "A_000001.SZ_60min"],
  "markets": [{ "market": "a", "stock_code": "000001" }]
}
```

**响应** `400` — 名称未录入
```json
{ "success": false, "message": "stock_codes 表中未找到 'xxx'，请先通过 POST /api/stock/code 录入该股票名称与代码映射" }
```

**响应** `400` — 缺少参数
```json
{ "success": false, "message": "缺少 stock 参数" }
```

> **注意**：工作流注册成功但数据表可能暂时为空——仅当调用发生在交易时段时才会拉取数据，非交易时段跳过数据获取。

---

## 量化决策

### POST /stock/decision

对已注册的股票运行量化算法并返回最新决策结果。支持代码或名称输入，名称可自动匹配多市场。

**请求**
```json
{ "stock": "000001", "interval": "daily" }
```
```json
{ "stock": "阿里巴巴", "interval": "daily" }
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `stock` | string | 是 | 股票代码或名称 |
| `interval` | string | 否 | 分析周期，默认 `daily`（可选 `120min`/`90min`/`60min`） |

**响应** `200` — 单市场
```json
{
  "success": true,
  "input": "000001",
  "interval": "daily",
  "count": 1,
  "results": [
    {
      "market": "a",
      "market_label": "A",
      "stock_code": "000001",
      "display_code": "000001.SZ",
      "timestamp": "2026-04-25 00:00:00",
      "close": 10.41,
      "position": 6.0,
      "position_label": "重仓",
      "core_long": false,
      "core_short": false,
      "resonance_buy": false,
      "resonance_sell": false,
      "top_structure_75": false,
      "top_structure_100": false,
      "bottom_structure_75": false,
      "bottom_structure_100": false,
      "high9_signal": false,
      "low9_signal": false,
      "position_history": { "current": 6.0, "prev": 10.0 }
    }
  ]
}
```

**响应** `200` — 多市场（如 "阿里巴巴" 港股 + 美股）
```json
{
  "success": true,
  "input": "阿里巴巴",
  "interval": "daily",
  "count": 2,
  "results": [
    { "market": "hk", "market_label": "HK", "stock_code": "09988", "display_code": "09988.HK", "position": 6.0, "position_label": "重仓", "core_long": false, "core_short": false, "resonance_buy": false, "resonance_sell": false, "top_structure_75": false, "top_structure_100": false, "bottom_structure_75": false, "bottom_structure_100": false, "high9_signal": false, "low9_signal": false, "close": 85.5, "timestamp": "2026-04-25" },
    { "market": "us", "market_label": "US", "stock_code": "BABA", "display_code": "BABA.US", "position": 4.0, "position_label": "轻仓", "core_long": false, "core_short": false, "resonance_buy": false, "resonance_sell": false, "top_structure_75": false, "top_structure_100": false, "bottom_structure_75": false, "bottom_structure_100": false, "high9_signal": false, "low9_signal": false, "close": 105.2, "timestamp": "2026-04-25" }
  ]
}
```

**字段说明**

| 字段 | 类型 | 说明 |
|------|------|------|
| `position` | float | 目标仓位：10（满仓）、6（重仓）、4（轻仓）、0（空仓） |
| `position_label` | string | 仓位中文描述 |
| `core_long` | bool | 核心做多信号：仓位 ≥ 4 且出现底部结构（75% 或 100%） |
| `core_short` | bool | 核心做空信号：仓位 ≤ 6 且出现顶部结构（75% 或 100%） |
| `resonance_buy` | bool | 共振买入：核心做多 + 低九序列 |
| `resonance_sell` | bool | 共振卖出：核心做空 + 高九序列 |
| `top_structure_75` | bool | 顶部结构 75% 形成（DIF 转向） |
| `top_structure_100` | bool | 顶部结构 100% 完成（DIF 下穿 DEA） |
| `bottom_structure_75` | bool | 底部结构 75% 形成 |
| `bottom_structure_100` | bool | 底部结构 100% 完成 |
| `high9_signal` | bool | 高九卖出序列形成 |
| `low9_signal` | bool | 低九买入序列形成 |

**响应** `400` — 数据不存在
```json
{ "success": false, "message": "stock_codes 表中未找到 'xxx'，请先通过 POST /api/stock/code 录入该股票名称与代码映射" }
```
```json
{ "success": false, "message": "缺少 stock 参数" }
```
```json
{ "success": false, "message": "interval 必须是 daily/120min/90min/60min" }
```

> **注意**：当输入名称匹配多个市场时，可能部分市场有数据、部分市场暂无（如港股休市但美股交易中）。此时 `results` 数组中对无数据的市场会返回 `error` 字段说明原因，有数据的市场返回正常决策结果。

---

## 工作流查询

### GET /stock/\<code\>/workflows

查询指定股票代码的所有工作流。

| 参数 | 位置 | 说明 |
|------|------|------|
| `code` | path | 股票内部代码（纯数字，如 `000001`） |

**响应** `200`
```json
{
  "success": true,
  "stock_code": "000001",
  "workflows": [
    {
      "id": "A_000001.SZ_daily",
      "market": "a",
      "stock_code": "000001",
      "display_code": "000001.SZ",
      "interval": "daily",
      "table": "A_000001.SZ_daily",
      "active": true,
      "created_at": "2026-04-25T12:00:00"
    }
  ]
}
```

### GET /workflows

获取所有已注册的工作流。

**响应** `200`
```json
{
  "success": true,
  "count": 4,
  "workflows": [
    {
      "id": "A_000001.SZ_daily",
      "market": "a",
      "stock_code": "000001",
      "display_code": "000001.SZ",
      "interval": "daily",
      "table": "A_000001.SZ_daily",
      "active": true,
      "created_at": "2026-04-25T12:00:00"
    }
  ]
}
```

### DELETE /workflows/\<workflow_id\>

删除指定工作流及其调度任务。

| 参数 | 位置 | 说明 |
|------|------|------|
| `workflow_id` | path | 工作流唯一标识 |

**响应** `200`
```json
{ "success": true, "message": "工作流 A_000001.SZ_daily 已删除" }
```

**响应** `404`
```json
{ "success": false, "message": "工作流 xxx 不存在" }
```

**响应** `500`
```json
{ "success": false, "message": "服务器错误: ..." }
```

---

## 工作流标识格式

`{市场}_{股票代码}_{周期}`

| 市场 | 前缀 | 示例 |
|------|------|------|
| A 股 | `A` | `A_000001.SZ_daily`、`A_600519.SS_daily` |
| 港股 | `HK` | `HK_00700.HK_daily` |
| 美股 | `US` | `US_AAPL.US_daily` |

周期：`daily`、`120min`、`90min`、`60min`

## 支持输入格式

| 市场 | 示例输入 |
|------|----------|
| A 股 | `000001`、`000001.SZ`、`600519`、`600519.SS`、`贵州茅台`（需先录入映射） |
| 港股 | `00700`、`00700.HK`、`阿里巴巴`（需先录入映射） |
| 美股 | `AAPL`、`AAPL.US`、`苹果`（需先录入映射） |
