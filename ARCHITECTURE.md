# Architecture

Phase 0 defines the technical spine for a greenfield crypto AI trading research platform. The MVP supports research, historical data management, backtesting, model experimentation, and paper trading only. Live trading is explicitly out of scope.

## Goals

- Build a reproducible research and backtest platform before adding trading automation.
- Keep raw market data immutable and auditable.
- Separate API, workers, storage, and experiment code so each can evolve independently.
- Prefer boring infrastructure: Python, Postgres, Redis, Parquet, and containerized services.
- Defer trading bot frameworks until the internal data and backtest spine is stable.

## Stack

- Runtime: Python 3.12
- Package and environment management: uv
- API: FastAPI
- Worker runtime: Python workers, initially process based, with Redis-backed queues
- Primary database: Postgres with TimescaleDB extension for time-series tables
- Cache and queue broker: Redis
- Raw archive: partitioned Parquet files on local or object storage
- Analytics notebooks and scripts: Python modules using the same domain services as the API
- UI: Streamlit later, after the core APIs and data model stabilize
- Trading frameworks: Freqtrade and FreqAI later, after ingestion, features, and backtests are reliable
- Deferred systems: Hummingbot and Condor
- Sandbox/testnet execution: deferred until execution phases; Phase 1 may expose disabled config placeholders only

## System Boundary

The platform owns:

- Exchange market data ingestion
- Raw data archiving
- Normalized candle and trade storage
- Feature generation
- Strategy research
- Backtest execution and result storage
- Paper trading simulation
- Experiment tracking metadata

The platform does not own in the MVP:

- Live order execution
- Custody, wallet, or key management for production trading
- Multi-exchange smart order routing
- Portfolio accounting for real capital
- Hummingbot or Condor integration

## High-Level Components

```text
                 +----------------+
                 | Research users |
                 +-------+--------+
                         |
                         v
+----------------+   +---+---------+       +----------------+
| Streamlit UI   |-->| FastAPI API |------>| Postgres       |
| later          |   |             |       | TimescaleDB    |
+----------------+   +---+---------+       +--------+-------+
                         |                          |
                         v                          |
                    +----+-----+                    |
                    | Redis    |                    |
                    | queues   |                    |
                    +----+-----+                    |
                         |                          |
                         v                          v
              +----------+-----------+      +-------+--------+
              | Python workers       |----->| Parquet archive|
              | ingest, features,    |      | raw immutable  |
              | backtests, paper     |      +----------------+
              +----------------------+
```

## Component Responsibilities

### FastAPI API

- Exposes project, dataset, backtest, paper session, and experiment endpoints.
- Validates requests and writes command records to Postgres.
- Enqueues long-running work in Redis.
- Returns job status, metrics, artifacts, and result summaries.
- Avoids running ingestion, feature generation, or backtests in request handlers.

### Workers

Workers execute long-running or repeatable tasks:

- Market data ingestion
- Raw archive writes
- Normalization into TimescaleDB
- Feature materialization
- Backtest runs
- Paper trading simulation ticks
- Model training and evaluation, once the data spine is ready

Workers must be idempotent where practical. Each worker job records its inputs, outputs, status, failure reason, and artifact paths.

### Agent Research Layer

Agents are structured research components. They read normalized data, features, model predictions, news/sentiment records, current paper portfolio state, and risk policy. They write `agent_reports` and, for trader-style agents only, `trade_proposals`.

Agent roles:

- `technical_analyst`: trend, momentum, volatility, volume, and indicator evidence.
- `price_action_analyst`: support/resistance, breakouts, liquidity sweeps, candle structure, and invalidation levels.
- `fundamental_analyst`: TVL, fees, revenue, DEX volume, stablecoin liquidity, supply, and protocol usage.
- `news_analyst`: confirmed events, rumors, duplicates, incident/news severity, and source quality.
- `sentiment_analyst`: time-window sentiment aggregates, sentiment direction, sample size, and confidence.
- `quant_model_analyst`: model prediction, model version, confidence, drift state, and recent realized accuracy.
- `trader`: combines analyst outputs into a trade proposal or explicitly recommends flat/no trade.
- `risk_manager`: critiques proposals and identifies violated risk rules; it does not approve execution.
- `portfolio_manager`: checks paper portfolio exposure, correlation, concentration, and open-position context.

Every agent output must validate against a strict JSON schema before persistence. Invalid JSON, unknown enum values, non-finite numbers, missing required fields, or schema version mismatches result in rejection and no trade proposal.

Agents must not import or call `packages/execution`, exchange clients, broker adapters, or order submission code. The only allowed side effects are writing report/proposal records through approved repositories or services.

Required analyst output fields:

```json
{
  "agent_name": "technical_analyst",
  "symbol": "BTC/USDT",
  "timeframe": "1h",
  "timestamp": "2026-06-27T12:00:00Z",
  "direction": "long",
  "confidence": 0.71,
  "score": 68,
  "summary": "Trend is bullish but volatility is elevated.",
  "evidence": [],
  "key_levels": {
    "support": [60200],
    "resistance": [62500],
    "invalidation": 59400
  },
  "risks": ["Resistance nearby"],
  "recommended_action": "consider_long"
}
```

Required trade proposal fields:

```json
{
  "symbol": "BTC/USDT",
  "timeframe": "1h",
  "side": "long",
  "entry": {"type": "limit", "price": 61000},
  "stop_loss": 59400,
  "take_profit": [{"price": 62500, "size_pct": 0.4}],
  "max_position_risk_pct": 0.5,
  "confidence": 0.68,
  "thesis": "Trend continuation after support retest.",
  "invalidation": "Close below 59400.",
  "required_confirmations": ["spread_bps < 10"],
  "source_agents": ["technical_analyst", "price_action_analyst"]
}
```

Required risk decision fields:

```json
{
  "proposal_id": "uuid",
  "decision": "reject",
  "reason": "spread above threshold",
  "max_position_size": null,
  "max_loss_usd": null,
  "violated_rules": ["spread_limit"],
  "warnings": [],
  "created_at": "2026-06-27T12:01:00Z"
}
```

### Postgres and TimescaleDB

Postgres stores relational metadata and normalized queryable time-series data.

Core relational tables:

- `exchanges`
- `assets`
- `trading_pairs`
- `ingestion_runs`
- `feature_sets`
- `agent_reports`
- `trade_proposals`
- `risk_decisions`
- `strategies`
- `backtest_runs`
- `backtest_metrics`
- `paper_sessions`
- `experiments`
- `artifacts`

Timescale hypertables:

- `candles`
- `trades`
- `order_book_snapshots`, optional after candles and trades are stable
- `features`, if feature volume remains queryable in Postgres

Large feature matrices may move to Parquet if database storage becomes inefficient.

#### Database Contract

All timestamps are timezone-aware UTC. External records store both provider event time and platform ingestion/availability metadata. Flexible payloads use JSONB, but identifiers, timestamps, numeric values used in queries, and status fields remain typed columns.

Core tables and constraints:

| Table | Key fields | Required constraints and indexes |
| --- | --- | --- |
| `assets` | id, symbol, name, chain, contract_address, coingecko_id, defillama_slug, category, is_active | unique provider ids where present; index symbol and active flag |
| `exchanges` | id, name, type, is_active | unique name |
| `trading_pairs` | id, exchange_id, base_asset_id, quote_asset_id, symbol, precision fields, min_order_size, is_active | unique exchange/symbol; index base/quote assets |
| `candles` | pair_id, timeframe, timestamp, open, high, low, close, volume, source, ingested_at, available_at | unique pair/timeframe/timestamp/source; index pair/timeframe/timestamp |
| `trades` | pair_id, source, trade_id, timestamp, side, price, amount, available_at | unique pair/source/timestamp/trade_id; index pair/source/available_at/timestamp |
| `orderbook_snapshots` | pair_id, timestamp, best_bid, best_ask, spread_bps, depth fields, imbalance, source, ingested_at, available_at | index pair/timestamp; reject negative prices/spreads |
| `derivatives_metrics` | pair_id, timestamp, funding_rate, open_interest, long_short_ratio, liquidation fields, source, ingested_at, available_at | index pair/timestamp; spot MVP may leave empty |
| `protocol_metrics` | asset_id, timestamp, tvl_usd, fees_usd, revenue_usd, dex_volume_usd, stablecoin_supply_usd, source, ingested_at, available_at | unique asset/timestamp/source; index asset/timestamp |
| `news_items` | id, asset_id nullable, source, title, url_hash, published_at, collected_at, available_at, content_hash, raw_text, relevance_score | unique url_hash/source and content_hash/source; index published_at and asset_id |
| `sentiment_scores` | news_item_id, asset_id nullable, model_name, label, score, confidence, reason, created_at | unique news/model/asset; index asset/created_at |
| `features` | pair_id, timeframe, timestamp, feature_set_name, features_json, features_hash, created_at, available_at | unique pair/timeframe/timestamp/feature_set_name; JSONB payload; index pair/timeframe/timestamp |
| `labels` | pair_id, timeframe, timestamp, horizon, forward_return, mfe, mae, label, created_at | unique pair/timeframe/timestamp/horizon; labels never join into features |
| `model_predictions` | pair_id, timeframe, timestamp, model_name, model_version, prediction, confidence, features_hash, created_at | index pair/timeframe/timestamp and model/version |
| `agent_reports` | id, pair_id, timestamp, agent_name, report_type, output_json, confidence, created_at | JSONB output; index pair/timestamp and agent_name |
| `trade_proposals` | id, pair_id, timestamp, source, side, entry_type, entry_price, stop_loss, take_profit_json, confidence, thesis, invalidation, raw_json, status | JSONB take-profit/raw fields; index pair/timestamp/status |
| `risk_decisions` | proposal_id, decision, reason, max_position_size, max_loss_usd, violated_rules_json, warnings_json, created_at | one active decision per proposal unless superseded explicitly |
| `backtest_runs` | id, strategy_name, config_json, start_time, end_time, metrics_json, artifact_path, created_at | JSONB config/metrics; index strategy_name and created_at |
| `orders` | id, environment, exchange, pair, side, order_type, amount, price, status, created_at, updated_at | environment limited to backtest/paper/sandbox in pre-live phases |
| `positions` | id, environment, pair, side, size, avg_entry, current_price, unrealized_pnl, realized_pnl, opened_at, closed_at | index environment/pair/opened_at |
| `risk_events` | id, severity, event_type, message, metadata_json, created_at | append-only JSONB metadata; index severity/event_type/created_at |

Schema implementation must include UTC validation, duplicate candle constraint tests, JSON schema validation at service boundaries, and indexes for all point-in-time reads.

### Redis

Redis is used for:

- Worker queues
- Short-lived job locks
- Progress updates
- Cache entries for frequently read metadata

Redis is not the system of record.

### Parquet Raw Archive

Raw exchange responses are stored as immutable Parquet datasets before normalization. This gives the platform a reproducible audit trail.

Recommended partition layout:

```text
archive/
  exchange=binance/
    market=spot/
      data_type=candles/
        symbol=BTC-USDT/
          timeframe=1m/
            date=2026-06-27/
              part-000.parquet
```

Raw files should include source metadata such as exchange, endpoint, symbol, timeframe, request window, fetch timestamp, and schema version.

## Data Flow

### Historical Ingestion

1. API creates an `ingestion_runs` record.
2. API enqueues the ingestion job in Redis.
3. Worker fetches exchange data for a bounded symbol and time range.
4. Worker writes immutable raw records to Parquet.
5. Worker normalizes valid records into TimescaleDB.
6. Worker records counts, gaps, duplicate handling, and artifact paths.

### Feature Generation

1. Researcher requests a feature set for a dataset and strategy context.
2. Worker reads normalized market data from TimescaleDB or raw Parquet as needed.
3. Worker writes feature metadata to Postgres.
4. Worker writes feature values to TimescaleDB or Parquet, based on expected volume.
5. Feature set records include code version, parameters, input dataset IDs, and output artifact paths.

### Backtesting

1. Researcher selects strategy, dataset, feature set, fees, slippage, and risk constraints.
2. API creates a `backtest_runs` record and enqueues execution.
3. Worker runs the backtest with deterministic inputs.
4. Worker stores trades, equity curve, metrics, logs, and artifacts.
5. API returns summaries and links to artifacts.

### Paper Trading

Paper trading is simulated execution against market data. In the MVP it must not place real orders.

1. User starts a paper session with a strategy and configured capital.
2. Worker advances the session from live or replayed market data.
3. Simulated orders, fills, positions, and PnL are stored in Postgres.
4. Session state can be stopped, resumed, and reviewed.

### Agent Proposal Flow

1. Feature and market snapshots are loaded using `available_at <= decision_time`.
2. Analyst agents write schema-validated reports.
3. Trader agent writes a schema-validated proposal or `flat`.
4. Risk gateway evaluates the proposal with deterministic checks.
5. Backtest or paper simulation may consume only approved or reduced proposals.
6. Rejected proposals are retained for analysis and never retried automatically.

## Framework Adoption

### Freqtrade and FreqAI

Freqtrade and FreqAI are deferred until after:

- Historical ingestion is reliable.
- Backtests are reproducible.
- Feature set lineage is recorded.
- Strategy interfaces are stable enough to map into framework-specific adapters.

Initial integration should be adapter based. Internal datasets and experiment records remain the source of truth.

### Hummingbot and Condor

Hummingbot and Condor are explicitly deferred. They are candidates for later execution or orchestration layers, not MVP dependencies.

## Service Interfaces

Initial API resource groups:

- `/health`
- `/version`
- `/config/summary`
- `/ingestion`
- `/market`
- `/features`
- `/agents`
- `/trade-proposals`
- `/strategy`
- `/risk`
- `/backtests`
- `/paper`
- `/models`

Long-running endpoints should create jobs and return job IDs. Job status should include `queued`, `running`, `succeeded`, `failed`, and `cancelled`.

## Repository Shape

Proposed initial layout:

```text
trading/
  apps/
    api/
    workers/
    dashboard/
  packages/
    core/
    data/
    features/
    agents/
    strategies/
    risk/
    backtesting/
    execution/
    observability/
  integrations/
    freqtrade/
    hummingbot/
    openbb/
  configs/
    assets.yml
    pairs.yml
    risk.yml
    features.yml
    agents.yml
  scripts/
  tests/
  migrations/
  docs/
  pyproject.toml
  uv.lock
```

Runtime data directories such as `data/`, `archive/`, and `reports/` are local development artifacts and should stay out of Git.

## Operational Rules

- Every generated artifact must be traceable to code version, parameters, and input dataset IDs.
- Raw archive writes are append-only.
- Normalized data may be repaired, but repairs must be captured in job metadata.
- Backtests must use explicit fee, slippage, and data window settings.
- Model training must never read future data relative to the training split.
- Live trading code, credentials, and order execution paths are not allowed in the MVP.
- Sandbox/testnet order submission is not allowed in Phase 1; only disabled configuration placeholders may exist.
