# exchange-monitor

公开市场数据采集框架（当前支持 Omni + Lighter），将可公开获取的数据统一写入 SQLite，便于回测、研究和交易所监控。

## 目标

- 只采集公开接口数据（不采私有账户数据）
- 统一 schema，避免后续新增交易所时改动核心表
- 采集层与存储层解耦，便于扩展 WS/增量采集

## 当前覆盖

### Omni（公开）

- `GET /metadata/stats`
- 入库：`instruments`、`fees`（静态 0）、`market_snapshots`、`quote_ladder_snapshots`
- 说明：Omni 是 RFQ 架构，无标准 L2/逐笔成交公开接口

### Lighter（公开）

- `GET /api/v1/orderBookDetails`
- `GET /api/v1/orderBookOrders`
- `GET /api/v1/recentTrades`
- `GET /api/v1/fundings`（失败时 fallback `funding-rates`）
- `GET /api/v1/candles`
- 入库：`instruments`、`fees`、`market_snapshots`、`orderbook_snapshots`、`trades`、`fundings`、`candles`

## 架构

- `clients/`：交易所 HTTP 客户端（只关心 API 调用）
- `collectors/`：交易所适配 + 统一字段规范化（Normalizer）
- `db/schema.py`：SQLite schema 与索引
- `db/repository.py`：统一入库接口（upsert + timeseries append）
- `service.py`：采集编排（Collector -> Repository）
- `main.py`：CLI

## 快速开始

```bash
# 运行测试
pytest -q

# 采集 Omni 公开数据
PYTHONPATH=src python -m exchange_monitor.main --db-path ./market_data.sqlite --only-omni

# 采集 Lighter 指定 market
PYTHONPATH=src python -m exchange_monitor.main --db-path ./market_data.sqlite --only-lighter --lighter-market-id 125

# 同时采集 Omni + Lighter
PYTHONPATH=src python -m exchange_monitor.main --db-path ./market_data.sqlite

# 开启实时日志 + 日志落盘（默认 logs/）
PYTHONPATH=src python -m exchange_monitor.main --db-path ./market_data.sqlite --log-level INFO

# 24x7 连续采集（每 60 秒一轮）
PYTHONPATH=src python -m exchange_monitor.main --db-path ./market_data.sqlite --log-level INFO --loop --interval-sec 60

# 企业级连续流式采集（Lighter WebSocket，不停机直到手动中断）
PYTHONPATH=src python -m exchange_monitor.main --db-path ./market_data.sqlite --stream-lighter --log-level INFO

# 测试时只订阅一个市场（例如 DUSK=125）
PYTHONPATH=src python -m exchange_monitor.main --db-path ./market_data.sqlite --stream-lighter --stream-market-id 125 --ws-snapshot-interval-sec 2

# 超低延迟写库（每条 ticker 都可落 snapshot；writer 10ms flush）
PYTHONPATH=src python -m exchange_monitor.main --db-path ./market_data.sqlite --stream-lighter --ws-snapshot-interval-sec 0 --ws-writer-flush-ms 10 --ws-writer-max-batch 200 --ws-shards 4 --ws-queue-drop-threshold 15000 --log-level INFO
```

心跳日志会输出延时分位统计（p50/p95/p99）：
- `lat_exch_recv`: 交易所时间戳 -> 本机接收
- `lat_recv_enq`: 本机接收 -> 入队
- `lat_queue_commit`: 入队 -> 提交写库
- `lat_batch_commit`: 单批次SQLite提交耗时

## 日志、run_id、重试统计

- 每次运行自动生成唯一 `run_id`（UTC 时间戳），可用 `--run-id` 自定义。
- 日志同时输出到控制台和文件：`logs/collector-<run_id>.log`。
- 每次运行结束会输出 HTTP 统计：`requests / retries / failures / recovered`。
- 若要跳过采集后数据库完整性检查，可加 `--skip-validation`。

## 数据库表

- `instruments`：交易对/合约定义（唯一键：`exchange + market_id`）
- `fees`：手续费快照（唯一键：`instrument_id + effective_at`）
- `market_snapshots`：BBO/mark/funding/OI/volume 快照
- `quote_ladder_snapshots`：Omni 报价阶梯（size_1k/size_100k/size_1m）
- `orderbook_snapshots`：Lighter 盘口快照原始数据
- `trades`：逐笔成交（唯一键：`instrument_id + trade_id`）
- `fundings`：资金费历史（唯一键：`instrument_id + exchange_ts`）
- `candles`：K 线（唯一键：`instrument_id + exchange_ts + resolution`）

## 新增交易所（最佳实践扩展方式）

1. 在 `clients/` 新建 `xxx_client.py`：只封装 API 调用。  
2. 在 `collectors/` 新建 `xxx_collector.py`：把交易所字段映射到统一结构。  
3. 在 `service.py` 注入新的 collector 并复用 `Repository` 入库方法。  
4. 新增针对 normalizer 的测试用例，保证字段兼容性。
