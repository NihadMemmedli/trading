# Crypto AI Trading Research Platform

Greenfield research platform for crypto market data ingestion, strategy research, AI-assisted signal evaluation, backtesting, and paper-trading simulation.

Current state: Phase 1 complete, Phase 2 data foundation in progress. The repository has its own local git history, a single runtime package, `trading`, FastAPI health/config/ingestion endpoints, safety-first settings validation, public OHLCV, trade, top-20 order book ingestion primitives, Binance public spot provider registry metadata, research-only funding/derivatives metric DTOs and storage primitives, raw Parquet archive support, Timescale-backed candle, trade, order book, and derivatives metric storage, deterministic offline fixtures, tests, and local Postgres/TimescaleDB and Redis services. It still has no trading engine, model pipeline, order execution, wallet, or custody code.

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
    }
  }'
```

`POST /backtests/runs` and `GET /backtests/runs/{run_id}` return full run details, including
the dataset lineage id and hash, reproducible report JSON, persisted trades, and persisted equity
curve:

```json
{
  "id": "00000000-0000-4000-8000-000000000011",
  "status": "succeeded",
  "dataset_id": 42,
  "dataset_hash": "dddd...",
  "metrics": {"trades_count": 1, "final_equity": "1001"},
  "report": {"report_hash": "...", "metrics": {"trades_count": 1}},
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
  ]
}
```

Use `GET /backtests/runs?limit=50` for a lightweight run list. List responses intentionally omit
`report`, `trades`, and `equity_curve`; fetch a specific run when those artifacts are needed.
They still include `dataset_id` and `dataset_hash` when lineage is available. Historical succeeded
runs created before artifact or dataset lineage persistence may return empty artifact arrays or
`dataset_id: null`.

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
