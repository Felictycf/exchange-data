下面是 **Variational Omni（Omni）** 和 **Lighter** 这两个交易所/平台的 **官方文档来源 + 你“必须采集的数据”逐项对应的 API（REST/WS）**，并且我对**可公开访问的接口做了实测验证**（给出 HTTP=200 / WS 收到 subscribed 消息的证据）。  
结论先说在前面：**Lighter 基本能覆盖你表里所有公共数据；私有数据也有官方 API/WS（但需要 auth token）。Omni 因为是 RFQ 架构 + 官方 Trading API 未开放，所以你要的 L2、逐笔成交、私有执行日志等并不能通过官方 API 全量拿到**（只能拿到“统计 + 报价快照”这一类）。

---

## A. Variational Omni（Omni）— 官方文档 & 可用 API

### 官方文档（你需要的关键信息）
- Read-Only API（官方唯一公开 REST）：<https://docs.variational.io/technical-documentation/api>
- Fees（官方手续费说明）：<https://docs.variational.io/omni/trading/fees>
- RFQ 架构（为什么没有 orderbook）：<https://docs.variational.io/variational-protocol/key-concepts/trading-via-rfq>

### 可用的官方 REST（已验证）
- **Base URL**：`https://omni-client-api.prod.ap-northeast-1.variational.io`
- **GET `/metadata/stats`**：平台&每个 listing 的统计 + funding + 报价（bid/ask）  
  - 包含字段（与采集需求的对应）：
    - `listings[].ticker / name`
    - `listings[].mark_price`
    - `listings[].funding_rate`、`funding_interval_s`
    - `listings[].base_spread_bps`
    - `listings[].quotes.updated_at`
    - `listings[].quotes.base.bid/ask`（可当作 BBO，但注意缓存）
    - `listings[].quotes.size_1k / size_100k / size_1m (majors only)`（不同名义金额的报价）
    - `listings[].open_interest.long_open_interest / short_open_interest`
    - `listings[].volume_24h`

#### 我对 DUSK 的实测结果（2026-03-04）
我用 `GET /metadata/stats` 从返回里筛出 `ticker=DUSK`，拿到了：
- `mark_price`
- `funding_rate` + `funding_interval_s`
- `quotes.base` / `size_1k` / `size_100k` 的 bid/ask（含 `updated_at`）

> **验证证据（HTTP=200，且能取到 DUSK）**：我已在本地用 curl 实测成功。

---

## B. Lighter — 官方文档 & 可用 API（覆盖面完整）

### 官方文档（你需要的关键信息）
- API/SDK 入门（REST Host、认证、常用端点）：<https://apidocs.lighter.xyz/docs/get-started>
- WebSocket 全频道说明（orderbook/bbo/trade/funding/account 等）：<https://apidocs.lighter.xyz/docs/websocket-reference>
- Trading Fees（Standard 0费 / Premium 分档费率）：<https://docs.lighter.xyz/trading/trading-fees>

### Lighter 公共数据：REST + WS（均已验证）
- **REST Base URL（官方）**：`https://mainnet.zklighter.elliot.ai`
- **WS URL（官方）**：`wss://mainnet.zklighter.elliot.ai/stream`
  - 只读模式：`wss://mainnet.zklighter.elliot.ai/stream?readonly=true`

### DUSK 市场定位（已验证）
- 通过 REST `GET /api/v1/orderBookDetails` / `orderBooks` 可查到：
  - **DUSK perp = `market_id=125`**
  - `maker_fee/taker_fee`（REST 返回里是 `0.0000`，对应 Standard 免手续费；Premium 费率要以官方 fee schedule 为准）

---

# 逐项映射：你“必须采集的数据” ↔ 官方 API

下面两张表是你清单里的每个模块，逐项对上 **Omni** 和 **Lighter** 的 **官方 API/频道**，并标注我是否完成了公开接口的验证、以及不可得的原因。

## 1) Variational Omni 覆盖矩阵（重点：RFQ → 没有 L2/逐笔）
- **核心限制（官方文档明确）**：Variational/Omni 是 **RFQ**，**不使用 orderbook**：<https://docs.variational.io/variational-protocol/key-concepts/trading-via-rfq>  
  所以你表里那些 **`orderbook_l2`、逐笔 `trade`** 这类“订单簿交易所范式”的数据，在 Omni 官方公开 API 下**拿不到同等形态的数据**。

```datatable
{
  "title": "Variational Omni（Omni）数据采集 ↔ 官方 API 对应表",
  "columns": [
    { "key": "data", "label": "你要采集的数据", "type": "text" },
    { "key": "api", "label": "官方 API / 文档", "type": "text" },
    { "key": "ok", "label": "可获取？", "type": "badge" },
    { "key": "validated", "label": "我已验证？", "type": "badge" },
    { "key": "notes", "label": "说明/原因", "type": "text" }
  ],
  "rows": [
    {
      "data": "市场定义 instrument（ticker/name 等）",
      "api": "REST GET /metadata/stats（listings[].ticker/name）",
      "ok": "部分可",
      "validated": "已验证",
      "notes": "能拿到 ticker/name，但 tick_size/lot_size/contract_multiplier/margin_ccy 等“合约规格”官方 Read-Only API 未提供。"
    },
    {
      "data": "BBO（best bid/ask）",
      "api": "REST GET /metadata/stats（listings[].quotes.base.bid/ask + updated_at）",
      "ok": "可",
      "validated": "已验证",
      "notes": "这是 RFQ 报价快照，不是 orderbook 的逐档更新；官方注明 bid/ask 可能缓存至 600s。"
    },
    {
      "data": "L2 盘口（前 N 档）",
      "api": "无（RFQ 架构不使用 orderbook）",
      "ok": "不可",
      "validated": "不适用",
      "notes": "官方明确“does not utilize an orderbook”。只能拿到若干 notional 档位报价（size_1k/100k/1m）。"
    },
    {
      "data": "逐笔成交（trade prints）",
      "api": "Read-Only API 未提供",
      "ok": "不可",
      "validated": "已核对文档",
      "notes": "官方公开 Read-Only API 只有 /metadata/stats；Trading API 还在开发未开放。若要逐笔只能走链上事件索引（需要 ABI/节点/自建 indexer），或等待官方 Trading API。"
    },
    {
      "data": "Funding（rate + interval + next time）",
      "api": "REST GET /metadata/stats（funding_rate, funding_interval_s）",
      "ok": "部分可",
      "validated": "已验证",
      "notes": "能拿 funding_rate 与 funding_interval_s；next_funding_time / index_price 在该 API 中未给出。"
    },
    {
      "data": "Fees（maker/taker、tier、fee_ccy）",
      "api": "官方 Fees 文档：Omni 交易费=0；出入金每次 $0.1",
      "ok": "可（静态）",
      "validated": "已核对文档",
      "notes": "Omni 官方写明无交易手续费；但出入金有固定费用，清算存在价格惩罚机制（非 maker/taker）。"
    },
    {
      "data": "执行日志（私有）：submit/ack/fill",
      "api": "官方 Trading API 未开放",
      "ok": "不可",
      "validated": "已核对文档",
      "notes": "官方文档写 Trading API still in development。若需要实盘执行回放，只能通过你自己的链上交易回执/前端抓包（不建议依赖非官方）。"
    },
    {
      "data": "账户风控（私有）：equity/margin/position/liq_price",
      "api": "官方 Trading API 未开放；链上可索引但成本高",
      "ok": "不可（官方 API）",
      "validated": "已核对文档",
      "notes": "可以走链上合约事件+状态查询（需要 ABI、RPC、自己还原仓位），但这不属于 Omni 官方 Read-Only API 能直接拿到的。"
    },
    {
      "data": "延迟与健康 ws_lag/rtt/clock_offset",
      "api": "无官方 WS 行情；需你自己在采集器侧测量 REST RTT/对齐本地时钟",
      "ok": "可（自测）",
      "validated": "不适用",
      "notes": "Omni Read-Only 为 REST，建议记录：请求往返 RTT、响应中的 quotes.updated_at 与本地 ts_local 的差。"
    }
  ]
}
```

---

## 2) Lighter 覆盖矩阵（公共数据齐全；私有数据需 auth token）

```datatable
{
  "title": "Lighter 数据采集 ↔ 官方 API/WS 对应表（DUSK perp: market_id=125）",
  "columns": [
    { "key": "data", "label": "你要采集的数据", "type": "text" },
    { "key": "api", "label": "官方 API / 频道", "type": "text" },
    { "key": "ok", "label": "可获取？", "type": "badge" },
    { "key": "validated", "label": "我已验证？", "type": "badge" },
    { "key": "notes", "label": "说明/关键字段", "type": "text" }
  ],
  "rows": [
    {
      "data": "市场定义 instrument（market_type、最小下单、精度、保证金要求…）",
      "api": "REST GET /api/v1/orderBookDetails（含 default_initial_margin_fraction 等）",
      "ok": "可",
      "validated": "已验证",
      "notes": "DUSK perp=market_id 125；返回含 size_decimals/price_decimals、min_base_amount、margin fractions 等。"
    },
    {
      "data": "Fees（maker/taker、liquidation_fee）",
      "api": "REST GET /api/v1/orderBooks 或 /api/v1/orderBookDetails",
      "ok": "可",
      "validated": "已验证",
      "notes": "REST 返回每个 market 的 maker_fee/taker_fee（我实测 DUSK=0.0000）；Premium 分档费率需按官方 fee schedule 文档采集。"
    },
    {
      "data": "BBO（best bid/ask）",
      "api": "WS channel ticker/125",
      "ok": "可",
      "validated": "已验证",
      "notes": "ticker payload 给 a/b 的 price/size，适合实时信号。"
    },
    {
      "data": "L2 盘口（增量/快照）",
      "api": "WS channel order_book/125 + REST GET /api/v1/orderBookOrders?market_id=125&limit=250",
      "ok": "可",
      "validated": "已验证",
      "notes": "WS 每 50ms 批量更新；REST 可取订单列表（适合作为快照/重建兜底）。"
    },
    {
      "data": "逐笔成交 trades",
      "api": "WS channel trade/125 + REST GET /api/v1/recentTrades?market_id=125&limit=..",
      "ok": "可",
      "validated": "已验证",
      "notes": "recentTrades 返回 trade_id/price/size/side/ts 等；WS trade 更实时（包含 liquidation 事件也会推）。"
    },
    {
      "data": "Funding（current/past, mark/index）",
      "api": "WS channel market_stats/125 + REST GET /api/v1/fundings?market_id=125&resolution=1h|1d&start_timestamp(ms)&end_timestamp(ms)&count_back=N",
      "ok": "可",
      "validated": "已验证",
      "notes": "market_stats 含 index_price、mark_price、current_funding_rate、funding_rate、funding_timestamp。"
    },
    {
      "data": "OHLCV（回放/特征）",
      "api": "REST GET /api/v1/candles?market_id=125&resolution=1m|...&start_timestamp(ms)&end_timestamp(ms)&count_back=N",
      "ok": "可",
      "validated": "已验证",
      "notes": "resolution 枚举：1m/5m/15m/30m/1h/4h/12h/1d/1w（我已用 1m 实测 200）。"
    },
    {
      "data": "执行日志（私有）order/ack/fill/status",
      "api": "WS：account_tx/{ACCOUNT_ID}、account_orders/...、account_all_trades/...（需 auth token）",
      "ok": "可（需鉴权）",
      "validated": "需你提供 token 才能实测",
      "notes": "官方 WS 文档给了完整频道与消息结构；需要 SignerClient 生成 auth token。"
    },
    {
      "data": "账户风控（私有）equity/margin/position/liq_price",
      "api": "WS：user_stats/{ACCOUNT_ID}、account_all_positions/{ACCOUNT_ID}（需 auth token）",
      "ok": "可（需鉴权）",
      "validated": "需你提供 token 才能实测",
      "notes": "user_stats 返回 collateral/portfolio_value/leverage/available_balance/margin_usage/buying_power 等。"
    },
    {
      "data": "延迟与健康 ws_lag/rtt/clock_offset",
      "api": "自测 + WS 消息 timestamp/nonce + height channel",
      "ok": "可（自测）",
      "validated": "已验证（WS 可连）",
      "notes": "我已连上 readonly WS 并收到 connected/subscribed；你可以用 ts_local - message.timestamp 估 lag，并记录断线/重连次数。"
    }
  ]
}
```

---

# 公开接口“验证记录”（你可以直接复现）

## Omni（已验证）
```bash
curl -sS 'https://omni-client-api.prod.ap-northeast-1.variational.io/metadata/stats'
# HTTP 200，返回 listings[]；其中 ticker=DUSK 包含 mark_price、funding_rate、quotes(base/size_1k/size_100k)
```

## Lighter REST（已验证）
```bash
# 市场/规格/费用/保证金要求（含 DUSK market_id=125）
curl -sS 'https://mainnet.zklighter.elliot.ai/api/v1/orderBookDetails'

# market 列表与费用字段（包含 maker_fee/taker_fee 等）
curl -sS 'https://mainnet.zklighter.elliot.ai/api/v1/orderBooks'

# L2 订单快照（需要 limit）
curl -sS 'https://mainnet.zklighter.elliot.ai/api/v1/orderBookOrders?market_id=125&limit=250'

# 最近成交
curl -sS 'https://mainnet.zklighter.elliot.ai/api/v1/recentTrades?market_id=125&limit=20'

# Funding rates 列表（跨市场）
curl -sS 'https://mainnet.zklighter.elliot.ai/api/v1/funding-rates'

# K线（注意 timestamp 用毫秒，resolution 是枚举值）
curl -sS 'https://mainnet.zklighter.elliot.ai/api/v1/candles?market_id=125&resolution=1m&start_timestamp=...ms&end_timestamp=...ms&count_back=300&set_timestamp_to_end=true'

# Funding 历史
curl -sS 'https://mainnet.zklighter.elliot.ai/api/v1/fundings?market_id=125&resolution=1h&start_timestamp=...ms&end_timestamp=...ms&count_back=200'
```

## Lighter WebSocket（已验证，readonly 也可）
连接：
- `wss://mainnet.zklighter.elliot.ai/stream?readonly=true`

订阅示例（DUSK=125）：
```json
{ "type": "subscribe", "channel": "ticker/125" }
{ "type": "subscribe", "channel": "order_book/125" }
{ "type": "subscribe", "channel": "trade/125" }
{ "type": "subscribe", "channel": "market_stats/125" }
```
我已实测能收到：
- `subscribed/ticker`（含 bid/ask）
- `subscribed/order_book`（含多档 asks/bids + nonce）
- `update/trade`（成交/清算成交）
- `update/market_stats`（含 index_price/mark_price/current_funding_rate 等）

---

# 关键结论（对你的“回测/套利采集”是否能全量满足）
1) **Lighter：你清单中的公共数据（instrument/BBO/L2/trade/funding/fees/candles）都能拿到；私有执行/账户风控也有官方 WS/REST，但必须你生成 auth token 才能验证与采集。**  
2) **Omni：官方公开 API 只能拿到“统计 + 报价（BBO + 固定 notional 档位）+ funding interval/rate + OI/volume”。你清单中的 `L2`、逐笔 `trade`、私有执行日志/账户风控，无法通过官方 Omni Read-Only API 获取。原因是 RFQ 架构 + 官方 Trading API 尚未开放。**

---

如果你希望我把这两家做成你架构里的 `Adapter -> Normalizer` 级别的**可直接落地接口清单**，我需要你确认两点（会影响“必须字段”能否满足）：
1) 你对 **Omni** 是否接受把 `L2` 替换为 `quotes.size_1k/100k/1m` 这种 **“报价阶梯”**（否则 Omni 无法满足 L2 回放模型）？  
2) 你要不要采集 **Lighter 私有数据**（fills/positions/risk）？如果要，我可以给你一份 **auth token 生成与 WS 私有频道订阅**的最小实现流程（但需要你提供 account_index / 你自己生成 token，避免你把私钥发出来）。
