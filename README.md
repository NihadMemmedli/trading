# Crypto AI Trading Research Platform

Greenfield research platform for crypto market data ingestion, strategy research, AI-assisted signal evaluation, backtesting, and paper-trading simulation.

Current state: Phase 1 and Phase 2 are complete, Phase 3 has a reproducible candle-backtest spine, and early Phase 4 feature/AI research slices are complete. The repository has its own local git history, a single runtime package, `trading`, FastAPI health/config/ingestion/dataset/backtest/feature-set/modeling/agent-signal endpoints, safety-first settings validation, public OHLCV, trade, top-20 order book ingestion primitives, Binance public spot provider registry metadata, research-only funding/derivatives metric DTOs and storage primitives, raw Parquet archive support, Timescale-backed candle, trade, order book, derivatives metric, feature row, split definition, model experiment, agent report, trade proposal, and risk decision storage, deterministic offline fixtures, synchronous persisted backtest runs, strategy metadata/version hashing, sizing controls, richer metrics, run events, tests, and local Postgres/TimescaleDB and Redis services. It still has no model adapters, training orchestration, paper-trading signal loop, order execution, wallet, or custody code.

## Safety Boundaries

- Live trading is disabled by default and must remain opt-in.
- The default environment is research-only: historical data, provider data endpoints, backtests, and paper trading.
- MVP market universe is `BTC/USDT`, `ETH/USDT`, and `SOL/USDT` until explicitly changed.
- No private keys, exchange API secrets, wallet seeds, or production credentials belong in Git.
- Any future order-placement code must require explicit configuration gates, dry-run checks, risk limits, and test coverage before it can execute.
- The project is not financial advice and must not be treated as an autonomous profit system.

## Planned Stack

- Python 3.12
- `uv` for dependency management, virtual environments, locking, and command execution
- `pytest` for tests
- `ruff` for linting and formatting
- `mypy` or `pyright` for static typing once package structure exists
- Exchange data integrations first; sandbox/testnet order submission is deferred until a later execution phase

## Setup

Install Python 3.12 and sync the locked environment:

```bash
uv python install 3.12
uv sync --all-groups
cp .env.example .env
make check
```

Run the API locally:

```bash
uv run uvicorn trading.apps.api.app:app --reload
```

Local infrastructure is optional for API-only checks and required for DB-backed ingestion verification:

```bash
make services-up
make services-logs
make services-down
```

## Backtest API Examples

Backtest runs require DB-backed candle data for the requested exchange, symbol, timeframe, and
point-in-time decision cutoff. Start local services, run the API, then create a deterministic
moving-average run:

```bash
curl -sS -X POST http://localhost:8000/backtests/runs \
  -H 'Content-Type: application/json' \
  -d '{
    "exchange": "binance",
    "symbol": "BTC/USDT",
    "timeframe": "1m",
    "start": "2026-01-01T00:00:00Z",
    "end": "2026-01-01T00:05:00Z",
    "decision_time": "2026-01-01T01:00:00Z",
    "generated_at": "2026-01-02T00:00:00Z",
    "initial_capital": "1000",
    "fee_bps": "1",
    "slippage_bps": "2",
    "strategy_name": "moving_average_crossover",
    "strategy_parameters": {
      "short_window": 1,
      "long_window": 2
    },
    "sizing": {
      "max_exposure": "1",
      "cash_reserve": "0",
      "min_trade_notional": "0"
    }
  }'
```

`POST /backtests/runs` and `GET /backtests/runs/{run_id}` return full run details, including
the dataset lineage id and hash, strategy version, sizing/risk config, reproducible report JSON,
persisted trades, persisted equity curve, and structured run events:

```json
{
  "id": "00000000-0000-4000-8000-000000000011",
  "status": "succeeded",
  "dataset_id": 42,
  "dataset_hash": "dddd...",
  "strategy_version": "1",
  "sizing": {"max_exposure": "1", "cash_reserve": "0", "min_trade_notional": "0"},
  "metrics": {"trades_count": 1, "final_equity": "1001", "sharpe_like": "0"},
  "report": {"report_hash": "...", "strategy_version": "1", "metrics": {"trades_count": 1}},
  "trades": [
    {
      "id": 1,
      "symbol": "BTC/USDT",
      "timestamp": "2026-01-01T00:01:00Z",
      "side": "buy",
      "quantity": "1",
      "fill_price": "100",
      "fee": "0.1",
      "slippage": "0.2"
    }
  ],
  "equity_curve": [
    {
      "id": 1,
      "timestamp": "2026-01-01T00:00:00Z",
      "equity": "1000"
    }
  ],
  "events": [
    {
      "id": 1,
      "timestamp": "2026-01-02T00:00:00Z",
      "level": "info",
      "event_type": "backtest.started",
      "message": "backtest run started",
      "metadata": {"strategy_name": "moving_average_crossover", "strategy_version": "1"}
    }
  ]
}
```

Use `GET /backtests/runs?limit=50` for a lightweight run list. List responses intentionally omit
`report`, `trades`, `equity_curve`, and `events`; fetch a specific run when those artifacts are needed.
They still include `dataset_id` and `dataset_hash` when lineage is available. Historical succeeded
runs created before artifact or dataset lineage persistence may return empty artifact arrays or
`dataset_id: null`.

Use `GET /datasets?limit=50` to inspect registered datasets created by ingestion or successful
backtests, and `GET /datasets/{dataset_id}` to fetch one dataset record:

```json
{
  "id": 42,
  "name": "backtest:binance:BTC/USDT:1m:2026-01-01T00:00:00Z:2026-01-01T00:05:00Z:2026-01-01T01:00:00Z",
  "dataset_hash": "dddd...",
  "decision_time": "2026-01-01T01:00:00Z",
  "artifact_id": null,
  "created_at": "2026-01-02T00:00:00Z",
  "backtest_run_count": 2
}
```

## AI Signal Contract APIs

The current Phase 4 slice persists validated research artifacts only:

- `POST /agents/reports`, `GET /agents/reports/{report_id}`, and `GET /agents/reports`
- `POST /trade-proposals`, `GET /trade-proposals/{proposal_id}`, and `GET /trade-proposals`
- `POST /risk/decisions`, `GET /risk/decisions/{proposal_id}`, and `GET /risk/decisions`

Analyst reports, trade proposals, and risk decisions must match strict schema versions before they are written. Invalid JSON shape, unknown enum values, non-finite numbers, bad selectors, schema version mismatches, or malformed long/flat proposal shapes are rejected before persistence. The records are stored in Postgres JSONB-backed tables created by Alembic migration `20260627_0011_ai_signal_contracts.py`.

These endpoints do not submit orders, create execution events, call exchange private APIs, or run model orchestration. Model adapters, feature pipeline evaluation, paper-trading integration, and execution paths are deferred to later Phase 4 and Phase 5+ work.

## Feature Set APIs

The current feature slice supports deterministic candle-derived MVP features tied to explicit dataset IDs:

- `POST /feature-sets`
- `GET /feature-sets/{feature_set_id}`
- `GET /feature-sets`

Feature sets record dataset hash, feature set hash, parameter hash, code version, selector metadata, feature names, and low-volume JSONB feature rows. Materialization reads only candles with `available_at <= decision_time` and rejects registered dataset hashes that cannot be reproduced from point-in-time data.

## Modeling Metadata APIs

The model experiment spine records split definitions and experiment results tied to explicit `dataset_id` and `feature_set_id` lineage:

- `POST /modeling/splits`
- `GET /modeling/splits/{split_definition_id}`
- `GET /modeling/splits`
- `POST /modeling/experiments`
- `GET /modeling/experiments/{experiment_id}`
- `GET /modeling/experiments`

Split definitions support holdout and walk-forward windows with `train`, `validation`, and `test` ranges. The service validates persisted feature rows for each window and rejects splits where rows are unavailable at the window `decision_time`. Experiment records store dataset ID, feature set ID, split definition ID, parameters, code version, metrics, status, timestamps, and deterministic lineage hashes.

These endpoints persist metadata only. They do not train models, call model providers, orchestrate prompts, create paper-trading signals, or touch execution paths.

## Configuration

Copy `.env.example` to `.env` for local development. Defaults are intentionally conservative:

- `APP_ENV=development`
- `TRADING_MODE=paper`
- `LIVE_TRADING_ENABLED=false`
- `ORDER_EXECUTION_ENABLED=false`
- `EXCHANGE_USE_SANDBOX=true`
- `SANDBOX_ORDER_EXECUTION_ENABLED=false`

Do not add real secrets to `.env.example`. Local `.env` files must stay untracked. Any config summary endpoint must redact keys, tokens, DSNs, passphrases, and provider secrets.

## Intended Architecture

Runtime Python imports live under the single `trading` package in `src/trading/`. Top-level folders such as `configs/`, `scripts/`, `migrations/`, and `integrations/` are project support folders, not additional import packages.

Planned modules:

- `trading.apps.api`: FastAPI service for health, version, and safe config in Phase 1; later ingestion, features, agents, strategy, risk, backtests, and paper trading
- `trading.apps.workers`: placeholder worker entrypoint in Phase 1; later background jobs for ingestion, feature generation, agent runs, backtests, and paper sessions
- `apps/dashboard`: Streamlit MVP dashboard after the core API stabilizes
- `trading.data`: provider adapters and registry metadata, normalized market data, order books, funding, fundamentals, news, and sentiment inputs
- `trading.data.offline`: deterministic fixture loading for offline research and future backtests
- `trading.features`: feature engineering, labeling, point-in-time joins, and feature store access
- `trading.agents`: strict-JSON analyst agents and trade proposal generation
- `trading.strategies`: deterministic strategy rules and AI-assisted signal adapters
- `trading.risk`: position sizing, stale-data checks, drawdown limits, exposure caps, kill switches, and audit rules
- `trading.backtesting`: portfolio simulation, fees, slippage, latency assumptions, and metrics
- Execution adapters are not part of the current phase. Do not add exchange order adapters, broker clients, wallet clients, or custody clients.
- `trading.observability`: structured logs, run metadata, metrics, and reproducible reports

## Development Rules

- Keep changes small and reviewable.
- Prefer typed, testable Python modules over notebooks for production logic.
- Treat notebooks as exploratory artifacts that must export reproducible code before promotion.
- Every strategy must document assumptions, data sources, benchmark, fees, slippage model, and failure modes.
- Any change that touches execution or risk controls must include tests.
- Agents are analysts only. They may persist reports and trade proposals, but they must not import or call execution adapters.
- Sandbox/testnet execution is not part of Phase 1. Phase 1 may define disabled config fields only.
