# Development Plan

This plan defines the first implementation path for a crypto AI trading research platform. The project starts as research-only and must not place live orders by default.

## Phase 0: Documentation and Guardrails

Status: complete after the Phase 0 documentation files and `.gitignore` are present.

Deliverables:

- `README.md` with current state, planned stack, setup workflow, and safety boundaries
- `DEVELOPMENT_PLAN.md` with phases, ownership model, and agent workflow
- `.env.example` with non-secret defaults and live trading disabled
- `.gitignore` with local secrets, data artifacts, caches, and virtual environments ignored
- Initial agreement that Python 3.12 and `uv` are the standard toolchain

Exit criteria:

- A new contributor can understand the project scope and safety posture.
- Configuration examples cannot accidentally enable live trading.
- Implementation phases are clear enough for parallel agents to pick disjoint tasks.

## Phase 1: Project Skeleton

Deliverables:

- `pyproject.toml` configured for Python 3.12, `uv`, `pytest`, `ruff`, and typing
- Top-level layout under `apps/`, `packages/`, `integrations/`, `configs/`, `scripts/`, and `tests/`
- Test layout under `tests/`
- Basic settings loader that reads environment variables safely
- CI-ready commands for lint, format, typecheck, and test

Exit criteria:

- `uv sync`, `uv run pytest`, and `uv run ruff check .` work from a clean checkout.
- Settings tests prove live trading and order execution default to disabled.
- Settings tests prove sandbox order submission, leverage, withdrawals, and custody are disabled by default.
- `GET /health`, `GET /version`, and `GET /config/summary` are implemented and tested.
- `/config/summary` redacts secrets and does not expose provider keys, tokens, passphrases, DSNs, or model API keys.
- No exchange, broker, or execution adapter is imported by API startup or agent modules.

## Phase 2: Data Foundation

Deliverables:

- Market data interfaces for candles, trades, order books, and funding rates
- Exchange market-data client abstraction; sandbox order submission remains deferred
- Historical data storage format and schema
- Database migrations matching the schema contract in `ARCHITECTURE.md`
- Data validation checks for gaps, duplicates, timestamp drift, and symbol normalization
- Reproducible sample dataset for tests

Exit criteria:

- Backtests can load deterministic historical data without network access.
- Data quality failures are explicit and test-covered.
- UTC timestamp validation, duplicate candle constraints, and point-in-time indexes are tested.

## Phase 3: Research and Backtesting

Deliverables:

- Strategy interface for deterministic and AI-assisted signals
- Backtesting engine with fees, slippage, portfolio accounting, and metrics
- Baseline strategies for benchmarking
- Experiment reports with parameters, dataset hashes, and performance metrics

Exit criteria:

- Every strategy run is reproducible.
- Results include drawdown, turnover, exposure, fees, and benchmark comparison.

## Phase 4: AI Signal Pipeline

Deliverables:

- Feature pipeline with strict train/test separation
- Model evaluation workflow with walk-forward validation
- Prompt/model adapters only where they add measurable value
- Guardrails against look-ahead bias, leakage, and overfitting
- Strict JSON schemas for analyst outputs, trade proposals, and risk decisions

Exit criteria:

- AI signals are evaluated against deterministic baselines.
- Promotion requires documented evidence, not anecdotal performance.
- Malformed agent output cannot create proposals or execution events.

## Phase 5: Paper Trading

Deliverables:

- Paper execution engine
- Portfolio state reconciliation
- Risk checks before simulated order placement
- Structured event log for decisions, rejected orders, fills, and risk events

Exit criteria:

- Paper trading runs continuously without live credentials.
- Risk controls can block simulated orders and explain why.

## Phase 6: Sandbox Execution

Deliverables:

- Exchange sandbox/testnet adapter
- Order lifecycle tracking
- Rate-limit handling and retry policy
- Reconciliation between local state and exchange sandbox state

Exit criteria:

- Sandbox orders require explicit non-default configuration.
- Integration tests use sandbox credentials supplied only through local environment or CI secrets.
- Sandbox submission is still blocked by kill switch, risk policy, and environment checks unless this phase is explicitly active.

## Phase 7: Live Trading Readiness

Live trading is out of scope until all previous phases are complete.

Required gates:

- `LIVE_TRADING_ENABLED=true`
- `ORDER_EXECUTION_ENABLED=true`
- `TRADING_MODE=live`
- Sandbox execution history reviewed
- Risk limits configured
- Manual approval recorded outside code
- Deployment rollback and kill-switch process tested

Exit criteria:

- Live trading cannot be enabled by a single flag.
- Operators can stop execution quickly and audit every decision.

## Agent Team Workflow

Agents should work in narrow, disjoint scopes and avoid rewriting files owned by another active task.

Roles:

- Planning agent: maintains `README.md`, `DEVELOPMENT_PLAN.md`, milestones, and safety rules.
- Platform agent: owns project skeleton, tooling, configuration, CI, and developer commands.
- Data agent: owns market data clients, schemas, storage, and data quality checks.
- Research agent: owns feature engineering, strategy interfaces, experiments, and model evaluation.
- Agent workflow agent: owns analyst prompts, JSON schemas, proposal generation, and no-execution boundaries.
- Backtesting agent: owns simulation accounting, fees, slippage, metrics, and reports.
- Risk agent: owns limits, kill switches, pre-trade checks, and audit requirements.
- Execution agent: owns paper trading, sandbox adapters, and order lifecycle code.

Coordination rules:

- Claim files before editing when multiple agents are active.
- Keep pull requests scoped to one phase or one module boundary.
- Do not modify unrelated dirty files.
- Document assumptions in the touched module or docs.
- Add tests for any executable behavior, especially configuration, data integrity, risk, and execution.
- Prefer boring interfaces that are easy to simulate over exchange-specific shortcuts.

Definition of done:

- Commands documented in `README.md` work or are clearly marked as planned.
- Tests cover the behavior being introduced.
- Defaults remain research-only and no-live-trading.
- Secrets are never committed.
