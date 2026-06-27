# Product Spec

This document defines the Phase 0 product scope for a crypto AI trading research platform. The MVP is a research, backtest, and paper trading system. It does not support live trading.

## Product Goal

Give a quantitative researcher a reliable environment to collect crypto market data, build features, test strategies, evaluate AI-assisted signals, and run paper trading sessions before any live execution work begins.

## Target Users

- Primary: quantitative researcher or engineer testing crypto strategies.
- Secondary: product or technical stakeholder reviewing experiment results.
- Later: operator monitoring paper and live systems after MVP scope expands.

## MVP Scope

The MVP includes:

- Historical market data ingestion for selected exchanges, symbols, and timeframes.
- Initial symbols: `BTC/USDT`, `ETH/USDT`, and `SOL/USDT`.
- Initial timeframes: `5m`, `15m`, `1h`, `4h`, and `1d`.
- Immutable raw data archive in Parquet.
- Normalized time-series storage in Postgres with TimescaleDB.
- Dataset registration and data quality metadata.
- Feature generation with lineage.
- AI analyst reports with strict JSON schemas.
- Trade proposals as research artifacts, not orders.
- Deterministic risk decisions for every actionable proposal.
- Deterministic backtesting.
- Backtest metrics and artifact storage.
- Paper trading simulation with no real order placement.
- FastAPI service layer for all core operations.
- Python worker layer for ingestion, features, backtests, and paper simulation.

The MVP excludes:

- Live trading.
- Real exchange order execution.
- Sandbox/testnet order submission in Phase 1.
- Production API key custody.
- Hummingbot integration.
- Condor integration.
- Streamlit UI, until the API and core data model stabilize.
- Freqtrade and FreqAI, until the internal data and backtest spine is reliable.

## Phase Plan

### Phase 0: Foundation Docs

- Define architecture.
- Define product scope.
- Record explicit non-goals and deferred integrations.

### Phase 1: Project Spine

- Create Python 3.12 project managed by uv.
- Add FastAPI app shell.
- Add settings management.
- Add Postgres, TimescaleDB, and Redis local development setup.
- Add migrations.
- Add worker entrypoint.
- Add base module layout under `apps/`, `packages/`, `integrations/`, `configs/`, `scripts/`, and `tests/`.
- Add health checks and basic test setup.

Phase 1 acceptance surface:

- `GET /health` returns service health without touching exchanges or providers.
- `GET /version` returns application name, version, and environment.
- `GET /config/summary` returns safe config only and redacts secrets.
- Settings validation proves live trading, order execution, leverage, withdrawals, custody, and sandbox order submission are disabled by default.

### Phase 2: Market Data Spine

- Implement exchange data adapters.
- Store raw responses as Parquet.
- Normalize candles into TimescaleDB.
- Track ingestion jobs, gaps, duplicates, and failures.
- Add dataset registry.

### Phase 3: Backtest Spine

- Define strategy interface.
- Implement deterministic backtest runner.
- Store trades, equity curve, metrics, logs, and artifacts.
- Add fee, slippage, position sizing, and risk settings.
- Add reproducibility metadata.

### Phase 4: Feature and AI Research

- Add feature set registry.
- Materialize features with lineage.
- Add train, validation, and test split support.
- Add model experiment records.
- Evaluate AI-assisted signals without live execution.

### Phase 5: Paper Trading

- Run strategies in simulated sessions.
- Store simulated orders, fills, positions, and PnL.
- Support replayed data first, then live market data without real orders.
- Add session controls: start, stop, resume, and review.

### Later Phases

- Add Streamlit UI for research workflows.
- Integrate Freqtrade and FreqAI through adapters.
- Reassess Hummingbot and Condor.
- Consider live trading only after paper trading, risk controls, auditability, and operational monitoring are proven.

## Functional Requirements

### Data Ingestion

- A user can create an ingestion job for exchange, market, symbol, timeframe, start time, and end time.
- The system stores raw source data in Parquet before normalization.
- The system writes normalized candles to TimescaleDB.
- The system records job status, record counts, gaps, duplicates, errors, and artifact paths.
- Failed jobs can be inspected and retried without corrupting existing data.

### Dataset Registry

- A user can define a dataset from symbols, timeframes, exchanges, and date ranges.
- A dataset records its source ingestion jobs and quality summary.
- Backtests and feature sets must reference explicit dataset IDs.

### Feature Generation

- A user can generate features for a dataset with named parameters.
- A feature set records code version, parameters, input dataset IDs, and output location.
- Feature generation must avoid future leakage.

### Strategy Research

- A user can register or select a strategy implementation.
- A strategy declares required market data, features, parameters, and risk settings.
- Strategy runs must be reproducible from stored metadata.

### Agent Research

- A user can run analyst agents for a symbol, timeframe, and decision timestamp.
- Every agent output must validate as strict JSON before it is stored.
- Agent reports can cite features, market records, news items, model predictions, and risk policy inputs.
- Trader agent may create trade proposals, but no agent may execute, size, or submit orders.
- Malformed agent output must be stored as an error event or rejected before persistence as a report/proposal.

### Risk Decisions

- Every non-flat trade proposal must be evaluated by the deterministic risk gateway.
- Every risk decision stores the decision, reason, violated rules, warnings, and timestamp.
- Only approved or reduced proposals may be consumed by backtest or paper simulation.
- Rejected proposals remain queryable for analysis.

### Backtesting

- A user can run a backtest for a strategy over a dataset.
- A backtest must include explicit initial capital, fees, slippage, sizing, and date range.
- The system stores trades, equity curve, drawdown, returns, Sharpe-like metrics, and logs.
- Results must link to the exact dataset, feature set, strategy version, and parameters.

### Paper Trading

- A user can start a paper session with simulated capital.
- The system creates simulated orders and fills only.
- The system stores positions, realized PnL, unrealized PnL, and session state.
- Paper trading must not call live exchange order endpoints.

## Non-Functional Requirements

- Reproducibility: data, parameters, code version, and artifacts must be linked.
- Auditability: raw market data is immutable and queryable by metadata.
- Reliability: long-running work runs in workers, not API request handlers.
- Data quality: ingestion records gaps, duplicates, and validation errors.
- Testability: domain logic should be testable without running the full API stack.
- Security: no live trading credentials are required or stored in the MVP.
- Secret safety: config summaries must redact API keys, tokens, passphrases, DSNs, and model provider secrets.
- Local development: a developer can run the stack locally with uv and containerized services.

## Key Workflows

### Run a Historical Backtest

1. Create ingestion jobs for required symbols and timeframes.
2. Verify dataset quality.
3. Register a dataset.
4. Generate required features.
5. Select strategy and parameters.
6. Run backtest.
7. Review metrics, trades, equity curve, logs, and artifacts.

### Run a Paper Session

1. Select a tested strategy.
2. Select data mode: replayed market data first, live market data later.
3. Configure simulated capital and risk settings.
4. Start paper session.
5. Review simulated orders, positions, PnL, and errors.
6. Stop or resume the session.

## Success Criteria

The MVP is successful when:

- A developer can ingest historical candle data for at least one exchange and symbol.
- Raw Parquet files and normalized TimescaleDB rows can be traced to the same ingestion job.
- A dataset can be registered and reused across feature generation and backtesting.
- A deterministic backtest can be rerun with the same result from the same inputs.
- Agent outputs and trade proposals validate against documented schemas.
- Every actionable proposal has a stored risk decision.
- A paper session can simulate orders without any live exchange order path.
- All major artifacts are linked to input data, parameters, and code version.

## Key Decisions

- Python 3.12 and uv are the baseline development environment.
- FastAPI is the API layer.
- Workers handle long-running jobs.
- Postgres with TimescaleDB stores metadata and queryable time-series data.
- Redis backs queues, locks, progress, and short-lived cache.
- Parquet is the immutable raw archive format.
- Streamlit is deferred until API and data workflows are stable.
- Freqtrade and FreqAI are deferred until after the internal data and backtest spine.
- Hummingbot and Condor are deferred.
- Live trading is excluded from the MVP.
- Sandbox/testnet order submission is deferred until later execution phases.
