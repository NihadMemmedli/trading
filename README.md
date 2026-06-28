# Crypto AI Trading Research Platform

Greenfield research platform for crypto market data ingestion, strategy research, AI-assisted signal evaluation, backtesting, and paper-trading simulation.

Current state: Phase 1 complete, Phase 2 data foundation in progress. The repository has its own local git history, a single runtime package, `trading`, FastAPI health/config/ingestion endpoints, safety-first settings validation, public OHLCV and trade ingestion primitives, raw Parquet archive support, Timescale-backed candle and trade storage, deterministic offline fixtures, tests, and local Postgres/TimescaleDB and Redis services. It still has no trading engine, model pipeline, order execution, wallet, or custody code.

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
- `trading.data`: provider adapters, normalized market data, order books, funding, fundamentals, news, and sentiment inputs
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
