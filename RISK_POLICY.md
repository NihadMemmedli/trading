# Risk Policy

Phase 0 is a deterministic, paper-first research environment. It must not place live orders, request leverage, custody assets, or perform withdrawals and transfers.

## Hard Invariants

These rules are mandatory and fail closed:

- Paper trading only. Live trading code paths are disabled in Phase 0.
- No leverage, margin, futures, perpetuals, options, or borrowed funds.
- No custody. The platform must not hold private keys, seed phrases, or exchange withdrawal credentials.
- No withdrawals, deposits, internal transfers, or address whitelisting.
- Read-only exchange API keys only.
- Deterministic risk checks must run before every simulated order.
- Agents cannot approve, size, submit, cancel, or modify orders.
- Stale, missing, future-timestamped, or lookahead-contaminated data blocks decisions.
- Every decision must be reproducible from versioned code, config, data snapshot, and model artifact.

## Execution Mode

Allowed modes:

| Mode | Purpose | External side effects |
| --- | --- | --- |
| `research` | Data analysis, feature generation, model experiments | None |
| `backtest` | Historical simulation with pinned data | None |
| `paper` | Forward simulation using live data and simulated fills | None |

Disallowed modes:

- `live`
- `margin`
- `futures`
- `perps`
- `options`
- `withdrawal`
- `custody`

Phase 1 may define configuration fields for future sandbox support, but it must not implement sandbox order submission. Sandbox/testnet execution belongs to a later execution phase and still requires deterministic risk approval.

If a mode is unknown, missing, or misspelled, treat it as disallowed.

## Configuration Gates

The platform starts in safe mode unless all required paper-trading gates are explicit:

```yaml
TRADING_MODE: paper
LIVE_TRADING_ENABLED: false
ALLOW_LEVERAGE: false
ALLOW_WITHDRAWALS: false
ALLOW_CUSTODY: false
```

Any attempt to set `LIVE_TRADING_ENABLED=true`, `ORDER_EXECUTION_ENABLED=true`, `SANDBOX_ORDER_EXECUTION_ENABLED=true`, `ALLOW_LEVERAGE=true`, `ALLOW_WITHDRAWALS=true`, or `ALLOW_CUSTODY=true` is a configuration error in Phase 0.

Exchange API credentials must be validated as read-only where the exchange exposes permission metadata. If permissions cannot be verified, the key is treated as unsafe and disabled.

## Data Safety Controls

Before a strategy can produce a decision, the data layer must verify:

- `event_time <= available_at <= decision_time`
- No record has an event timestamp in the future relative to the decision clock.
- All required datasets satisfy their freshness SLA.
- The strategy only reads data available at or before `decision_time`.
- Feature windows are closed on completed intervals only.
- Labels, target returns, future prices, and post-decision outcomes are unavailable to feature builders.

If any check fails, the only permitted action is `NO_DECISION`.

## Agent Safety Controls

Agent outputs are research inputs, not approvals. The platform must reject or ignore an agent output when:

- the response is not valid JSON;
- required fields are missing;
- enum values are outside the documented schema;
- numeric values are non-finite, negative where impossible, or outside configured bounds;
- timestamps are missing, timezone-naive, or later than the decision clock;
- the output attempts to override risk policy or request order execution;
- external news/social text appears to contain prompt-injection instructions.

Malformed analyst output may be stored as an error event for debugging, but it must not create a trade proposal. Malformed trade proposals must produce `NO_DECISION`.

## No-Lookahead Rules

Backtests, paper trading, and model training must separate:

- `event_time`: when the market or external event happened.
- `ingested_at`: when the platform stored the record.
- `available_at`: when the platform could have used the record.
- `decision_time`: when the strategy made a decision.

Consumers query by `available_at <= decision_time`. They must not query by final dataset partition, file modification time, or post-run availability.

Model training must use time-based splits. Random splits are disallowed for time-series prediction unless the task is explicitly non-predictive.

## Deterministic Pre-Trade Checks

Every simulated order must pass the same ordered checks:

1. Mode is `paper`.
2. Strategy is enabled in config.
3. Data quality state is `OK`.
4. Signal timestamp matches the decision clock.
5. Symbol and venue are allowlisted.
6. Market is spot-only.
7. Order side is allowed.
8. Order type is allowed.
9. Position size is within configured limits.
10. Portfolio exposure is within configured limits.
11. Daily loss and drawdown limits are not breached.
12. Kill switch is inactive.
13. Proposal source is schema-valid and not generated from rejected or stale agent output.

The first failed check returns a structured rejection reason. Rejections are logged and are not retried automatically.

## Default Limits

Phase 0 limits are intentionally conservative and may be tightened per strategy:

| Limit | Default |
| --- | ---: |
| Max position per asset | 10% of paper equity |
| Max notional per order | 2% of paper equity |
| Max total crypto exposure | 50% of paper equity |
| Max stablecoin exposure per issuer | 40% of paper equity |
| Max daily paper loss | 2% of paper equity |
| Max paper drawdown | 10% of starting paper equity |
| Max open positions | 10 |
| Min quote liquidity check | Required |

When limits conflict, apply the strictest limit.

## Allowed Simulated Orders

Allowed:

- Spot buy and sell orders.
- Marketable simulated orders using documented fill assumptions.
- Limit simulated orders with deterministic fill rules.

Disallowed:

- Short sales.
- Borrowing.
- Leveraged tokens unless explicitly classified as blocked assets.
- Derivatives.
- Cross-margin or isolated-margin products.
- Any order requiring live exchange submission.

## Paper Fill Policy

Paper fills must be deterministic:

- Use provider market data available at `decision_time`.
- Apply configured fees and slippage.
- Reject fills when price, liquidity, or spread data is stale.
- Record the fill model version.
- Do not assume fills inside a candle unless the simulation policy defines a deterministic intrabar rule.

Backtest and paper results must disclose fill assumptions with every run summary.

## Kill Switches

The system must return `NO_DECISION` or reject simulated orders when:

- Data freshness checks fail.
- Provider clocks disagree beyond tolerance.
- Portfolio accounting fails to reconcile.
- Daily loss limit is breached.
- Drawdown limit is breached.
- Strategy emits invalid or non-finite values.
- Required provider credentials are unsafe or over-permissioned.
- Any live trading flag is enabled.
- Any sandbox order-execution flag is enabled before the sandbox execution phase.

Kill switch state persists until explicitly cleared by an operator action recorded in the audit log.

## Audit Requirements

Every decision records:

```yaml
run_id: string
strategy_id: string
model_version: string | null
code_version: string
config_hash: string
data_snapshot_id: string
decision_time: timestamp
input_sources: string[]
risk_checks: object[]
decision: BUY | SELL | HOLD | NO_DECISION
rejection_reason: string | null
```

Audit records are append-only. Corrections are new records linked to the original decision.

## Phase 0 Exit Criteria

Phase 0 remains paper-only until all of the following are true:

- Data freshness and no-lookahead checks are covered by automated tests.
- Risk checks are deterministic and independently tested.
- Paper fills and portfolio accounting reconcile across replay.
- Read-only credential validation is implemented.
- An operator review approves a separate live-trading design document.

Live trading is not enabled by editing this policy. It requires a new phase, a new threat model, and explicit implementation work.
