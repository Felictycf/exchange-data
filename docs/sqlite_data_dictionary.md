# SQLite 数据字典（公开行情采集）

本文档解释当前数据库中每一张表、每一个字段的含义、作用，以及可以做哪些分析。

## 1. `instruments`

用途：交易标的主数据表（维表）。所有行情表都通过 `instrument_id` 关联到它。

| 字段 | 类型 | 含义 | 作用/可以做什么 |
|---|---|---|---|
| `id` | INTEGER PK | 标的内部主键 | 作为其他表外键，统一关联 |
| `exchange` | TEXT NOT NULL | 交易所标识（如 `omni`、`lighter`） | 做多交易所对比、分库统计 |
| `market_id` | TEXT NOT NULL | 交易所侧市场 ID | 对接原始 API 的唯一市场标识 |
| `symbol` | TEXT NOT NULL | 交易符号（如 `DUSK-PERP`） | 人类可读展示、策略筛选 |
| `base_asset` | TEXT | 基础资产 | 做资产维度聚合（如同币跨所） |
| `quote_asset` | TEXT | 计价资产 | 统一换算与币种过滤 |
| `status` | TEXT | 市场状态（ACTIVE/UNKNOWN 等） | 过滤停牌/不可交易市场 |
| `instrument_type` | TEXT | 合约类型（`perp`、`rfq_perp`） | 区分不同微观结构策略 |
| `price_decimals` | INTEGER | 价格精度 | 下单精度检查、报价归一 |
| `size_decimals` | INTEGER | 数量精度 | 头寸管理、下单约束 |
| `min_size` | REAL | 最小下单量 | 回测约束、实盘可成交性判断 |
| `raw_json` | TEXT | 原始返回 JSON | 回溯字段映射、排查解析问题 |
| `created_at` | TEXT | 记录创建时间（UTC） | 数据血缘、增量同步诊断 |
| `updated_at` | TEXT | 最近更新时间（UTC） | 监控标的元信息变化 |

约束：`UNIQUE(exchange, market_id)`，确保同交易所市场唯一。

---

## 2. `fees`

用途：手续费快照。用于回测净值、滑点后真实收益估计。

| 字段 | 类型 | 含义 | 作用/可以做什么 |
|---|---|---|---|
| `id` | INTEGER PK | 主键 | 内部索引 |
| `instrument_id` | INTEGER FK | 对应 `instruments.id` | 关联具体市场 |
| `effective_at` | TEXT NOT NULL | 生效时间 | 按时间回放不同费率制度 |
| `maker_fee` | REAL | 挂单费率 | 成本模型 |
| `taker_fee` | REAL | 吃单费率 | 成本模型 |
| `fee_ccy` | TEXT | 手续费计价币种 | 多币种成本归一 |
| `raw_json` | TEXT | 原始费率信息 | 费率来源审计 |

约束：`UNIQUE(instrument_id, effective_at)`，同时间点只保留一条费率快照。

---

## 3. `market_snapshots`

用途：市场状态快照（BBO、mark、funding、OI、24h量）。适合做横截面监控与因子回测。

| 字段 | 类型 | 含义 | 作用/可以做什么 |
|---|---|---|---|
| `id` | INTEGER PK | 主键 | 内部索引 |
| `instrument_id` | INTEGER FK | 对应市场 | 与标的表关联 |
| `collected_at` | TEXT NOT NULL | 采集器本地时间 | 采集延迟评估、对齐外部数据 |
| `exchange_ts` | TEXT | 交易所时间 | 事件时序对齐 |
| `best_bid` | REAL | 最优买价 | 点差、微观结构信号 |
| `best_ask` | REAL | 最优卖价 | 点差、微观结构信号 |
| `mark_price` | REAL | 标记价格 | 风险与资金费相关分析 |
| `index_price` | REAL | 指数价格 | 偏离监控（mark-index basis） |
| `funding_rate` | REAL | 当前/最近资金费率 | 资金费套利与方向因子 |
| `funding_interval_sec` | INTEGER | 资金费结算间隔（秒） | 年化换算、时间对齐 |
| `open_interest_long` | REAL | 多头 OI | 情绪与拥挤度分析 |
| `open_interest_short` | REAL | 空头 OI | 情绪与拥挤度分析 |
| `volume_24h` | REAL | 24h 成交量 | 流动性过滤、市场分层 |
| `raw_json` | TEXT | 原始快照 JSON | 解析异常回溯 |

索引：`idx_snapshots_instrument_collected(instrument_id, collected_at)`，支持按市场按时间查询。

---

## 4. `quote_ladder_snapshots`

用途：Omni（RFQ）报价阶梯快照（按名义金额档位，如 `size_1k/100k/1m`）。

| 字段 | 类型 | 含义 | 作用/可以做什么 |
|---|---|---|---|
| `id` | INTEGER PK | 主键 | 内部索引 |
| `instrument_id` | INTEGER FK | 对应市场 | 与 `instruments` 关联 |
| `collected_at` | TEXT NOT NULL | 本地采集时间 | 追踪报价更新频率 |
| `exchange_ts` | TEXT | 交易所报价时间 | 新鲜度判断 |
| `tier` | TEXT NOT NULL | 报价档位名称 | 不同名义规模冲击成本分析 |
| `bid` | REAL | 该档位买价 | 交易成本曲线 |
| `ask` | REAL | 该档位卖价 | 交易成本曲线 |
| `raw_json` | TEXT | 原始 tier 数据 | 档位语义回溯 |

说明：此表是 Omni 替代传统 L2 的核心数据来源。

---

## 5. `orderbook_snapshots`

用途：Lighter 盘口快照存档（原始结构）。

| 字段 | 类型 | 含义 | 作用/可以做什么 |
|---|---|---|---|
| `id` | INTEGER PK | 主键 | 内部索引 |
| `instrument_id` | INTEGER FK | 对应市场 | 与 `instruments` 关联 |
| `collected_at` | TEXT NOT NULL | 本地采集时间 | 快照频率与延迟评估 |
| `exchange_ts` | TEXT | 交易所时间 | 事件时序对齐 |
| `depth` | INTEGER | 快照深度（bids+asks 条数） | 流动性强弱监控 |
| `raw_json` | TEXT | 原始盘口 JSON | 重建更细盘口特征 |

---

## 6. `trades`

用途：逐笔成交表（去重后）。适合成交驱动策略、冲击成本和流动性分析。

| 字段 | 类型 | 含义 | 作用/可以做什么 |
|---|---|---|---|
| `id` | INTEGER PK | 主键 | 内部索引 |
| `instrument_id` | INTEGER FK | 对应市场 | 与标的关联 |
| `trade_id` | TEXT NOT NULL | 交易所成交 ID | 去重关键字段 |
| `exchange_ts` | TEXT | 成交时间 | 高频序列回放 |
| `price` | REAL | 成交价 | VWAP/滑点/冲击分析 |
| `size` | REAL | 成交量 | 成交流强度特征 |
| `side` | TEXT | 成交方向（buy/sell） | 主动买卖压力因子 |
| `is_liquidation` | INTEGER NOT NULL | 是否强平成交（0/1） | 风险事件识别 |
| `raw_json` | TEXT | 原始成交 JSON | 字段兼容与审计 |

约束：`UNIQUE(instrument_id, trade_id)`，保证幂等写入。

索引：`idx_trades_instrument_exchange_ts(instrument_id, exchange_ts)`。

---

## 7. `fundings`

用途：资金费历史表。用于资金费回测、carry 策略和拥挤度研究。

| 字段 | 类型 | 含义 | 作用/可以做什么 |
|---|---|---|---|
| `id` | INTEGER PK | 主键 | 内部索引 |
| `instrument_id` | INTEGER FK | 对应市场 | 与标的关联 |
| `exchange_ts` | TEXT NOT NULL | 资金费时间 | 时间序列回测 |
| `funding_rate` | REAL | 资金费率 | 年化、分位数、择时 |
| `mark_price` | REAL | 对应 mark 价格 | 费率与价格联动分析 |
| `index_price` | REAL | 对应 index 价格 | basis 监控 |
| `raw_json` | TEXT | 原始 funding JSON | 规则差异回溯 |

约束：`UNIQUE(instrument_id, exchange_ts)`，避免重复资金费点位。

---

## 8. `candles`

用途：K 线聚合表（OHLCV）。用于绝大多数中低频策略回测与特征工程。

| 字段 | 类型 | 含义 | 作用/可以做什么 |
|---|---|---|---|
| `id` | INTEGER PK | 主键 | 内部索引 |
| `instrument_id` | INTEGER FK | 对应市场 | 与标的关联 |
| `exchange_ts` | TEXT NOT NULL | K 线时间（通常为 bar 起点） | 时间轴回放 |
| `resolution` | TEXT NOT NULL | 周期（如 `1m/5m/1h/1d`） | 多周期因子 |
| `open` | REAL | 开盘价 | 技术指标输入 |
| `high` | REAL | 最高价 | 波动率/区间特征 |
| `low` | REAL | 最低价 | 波动率/区间特征 |
| `close` | REAL | 收盘价 | 收益率/信号计算 |
| `volume` | REAL | 成交量 | 量价因子 |
| `raw_json` | TEXT | 原始 candle JSON | 兼容多交易所字段差异 |

约束：`UNIQUE(instrument_id, exchange_ts, resolution)`。

索引：`idx_candles_instrument_resolution_ts(instrument_id, resolution, exchange_ts)`。

---

## 推荐分析路径（你后续可直接用）

1. 跨交易所对比：`instruments` + `market_snapshots`（同 `base_asset`）做价差与 funding 差。  
2. 成本建模：`fees` + `trades` + `quote_ladder_snapshots`，得到真实可交易收益。  
3. 事件驱动策略：`trades.is_liquidation` + `fundings` + `candles` 做风险事件回测。  
4. 监控看板：按 `exchange` 聚合 `snapshots/trades/fundings` 的新鲜度和覆盖率。

## 注意事项

- `raw_json` 是审计和回溯关键字段，不建议删除。  
- `exchange_ts` 可能为空（上游接口限制），应优先用 `collected_at` 保底排序。  
- Omni 是 RFQ 架构，`quote_ladder_snapshots` 是替代 L2 的主要来源。  
- 私有账户数据未入库（按当前需求），未来可新增私有表并复用 `instrument_id` 体系。
