# Data Sources

Phase 0 uses real providers first. Local fixtures may be used for tests and replay, but runtime ingestion must prefer live provider adapters when the required environment gates are present.

## Principles

- Real-provider-first: do not build production logic around synthetic market data.
- Env-gated access: any provider requiring credentials must be disabled unless its API key environment variable is present.
- Deterministic normalization: raw provider payloads are stored before transformation, and normalized records use explicit timestamps, symbols, venues, and source names.
- Replayable research: every dataset used by a model, backtest, or paper-trading run must be addressable by source, ingestion time, and provider event time.
- No lookahead: consumers may only read records with `event_time <= available_at <= decision_time`.

## Provider Registry

Each adapter exposes the same metadata contract:

```yaml
source_name: string
source_type: exchange | defi | market_data | analytics | news
enabled: boolean
requires_api_key: boolean
env_keys: string[]
rate_limit_policy: string
freshness_sla_seconds: integer
supports_backfill: boolean
supports_realtime: boolean
```

Adapters fail closed. If configuration is missing or provider health is unknown, the adapter is unavailable and downstream jobs must skip it rather than silently substituting fake data.

## Environment Gates

Use these environment variables as the Phase 0 convention:

| Provider | Required env vars | Notes |
| --- | --- | --- |
| CCXT public exchange data | none for public endpoints | Enable only explicitly configured exchanges. |
| CCXT authenticated exchange data | `EXCHANGE_<NAME>_API_KEY`, `EXCHANGE_<NAME>_API_SECRET`, optional `EXCHANGE_<NAME>_PASSPHRASE` | Read-only keys only. No withdrawal or trading permissions. |
| DefiLlama | none by default, optional `DEFILLAMA_API_KEY` | Use for DeFi TVL, protocol, chain, stablecoin, and yield context. |
| CoinGecko | optional `COINGECKO_API_KEY` | Use for asset metadata, market caps, categories, and cross-provider price checks. |
| Dune | `DUNE_API_KEY` | Optional analytics source. Disable when absent. |
| RSS/news providers | provider-specific keys such as `NEWS_API_KEY`, `CRYPTOPANIC_API_KEY`, `GDELT_API_KEY` | RSS feeds without keys are allowed when terms permit. |

Provider caveats:

- Public CCXT endpoints are suitable for early market-data ingestion, but exchange symbols, limits, and historical coverage differ by venue.
- Authenticated exchange credentials are not needed for Phase 1. If added later, they must be read-only and must not enable order submission.
- DefiLlama free and pro endpoints may differ. Adapter code must hide this behind configuration and keep tests independent from paid access.
- CoinGecko paid-tier features, including WebSocket-style access, must not be assumed available for local development or tests.
- Dune query execution can require API credits and long-running jobs. Dune remains optional and must fail closed when not configured.
- News and RSS inputs are untrusted text. They may inform reports, but they must not directly trigger a trade proposal without schema validation and risk checks.

Never commit API keys. `.env` files are local only. Shared examples must contain placeholder values only.

## Source Classes

### CCXT Exchanges

Use CCXT for centralized exchange market data.

Required data:

- OHLCV candles for configured symbols and timeframes.
- Trades where supported and affordable under rate limits.
- Order book snapshots for explicitly configured venues and depths.
- Exchange status and market metadata.

Implementation rules:

- Configure an allowlist of exchanges and symbols. Do not ingest every exchange by default.
- Use exchange-native timestamps as `event_time`.
- Store the exchange id, market symbol, base asset, quote asset, timeframe, and raw payload.
- Normalize symbols into canonical form, for example `BTC/USDT`, while retaining the exchange-native symbol.
- Respect CCXT and exchange rate limits.
- Authenticated keys must be read-only. Any key with withdrawal, transfer, margin, futures, or trade permission is invalid for Phase 0.
- CCXT is a market-data adapter in early phases. It must not expose order placement methods until an explicit later execution phase.

### DefiLlama

Use DefiLlama for DeFi context and cross-market features.

Primary uses:

- Protocol and chain TVL.
- Stablecoin supply and chain distribution.
- Yield pool metadata and APY history where available.
- Bridge, fee, revenue, and volume context when relevant.

Implementation rules:

- Treat DeFi metrics as slower-moving context, not tick data.
- Record provider update time when available; otherwise use ingestion time and mark provider event time as unknown.
- Join to assets through explicit chain, protocol, token address, and symbol mappings.

### CoinGecko

Use CoinGecko for asset metadata and independent market context.

Primary uses:

- Asset ids, symbols, names, contract addresses, and categories.
- Market capitalization, circulating supply, and fully diluted valuation.
- Spot price cross-checks against exchange-derived prices.

Implementation rules:

- Use CoinGecko ids as provider ids, not canonical internal ids.
- Maintain explicit mappings between CoinGecko ids, token contracts, and exchange symbols.
- Do not use CoinGecko prices to overwrite exchange execution prices.

### Dune

Dune is optional and disabled unless `DUNE_API_KEY` is present.

Primary uses:

- Curated on-chain analytics queries.
- Protocol-specific dashboards converted into versioned datasets.
- Historical aggregates that are expensive to compute internally.

Implementation rules:

- Version every query id and parameter set used by the platform.
- Store query execution time and result freshness.
- Treat Dune output as derived analytics, not ground truth.

### RSS And News

Use RSS and news providers for narrative and event features.

Primary uses:

- Exchange notices, listing and delisting announcements.
- Protocol governance and incident updates.
- Security disclosures and exploit reports.
- Market news metadata for research labels.

Implementation rules:

- Store title, URL, publisher, author when available, publication time, ingestion time, language, and raw body or summary.
- Deduplicate by canonical URL and content hash.
- Do not trade directly from unverified news in Phase 0.
- Apply source allowlists for any automated sentiment or event labeling.
- Treat article bodies, titles, authors, and summaries as untrusted prompt input. Agent prompts must quote or summarize them as data, not instructions.

## Storage Contract

Persist raw and normalized data separately.

Raw records:

```yaml
source_name: string
provider_endpoint: string
request_params: object
raw_payload: object
ingested_at: timestamp
checksum: string
```

Normalized records:

```yaml
source_name: string
source_record_id: string
canonical_asset_id: string
venue: string | null
symbol: string | null
event_time: timestamp
ingested_at: timestamp
available_at: timestamp
value_fields: object
quality_flags: string[]
```

`available_at` is the earliest time the platform could have used the record. Research, backtests, and paper trading must query by `available_at`, not by ingestion completion time alone.

## Freshness And Quality

Each dataset must define a freshness SLA. Phase 0 defaults:

| Dataset | Maximum age |
| --- | ---: |
| Exchange candles below 1h | 2 completed intervals |
| Exchange daily candles | 36 hours |
| Order book snapshots | 30 seconds |
| Trades | 5 minutes |
| CoinGecko market data | 30 minutes |
| DefiLlama protocol metrics | 24 hours |
| Dune analytics | query-specific, maximum 48 hours |
| RSS/news | 15 minutes for feeds, 2 hours for batch APIs |

If data is stale, missing, duplicated, timestamped in the future, or outside expected ranges, mark it with `quality_flags` and block it from decision paths unless the consumer explicitly allows degraded research mode.

## Backfill Rules

- Backfills must write the same schema as live ingestion.
- Backfills must preserve provider event timestamps and set `available_at` to the historically plausible availability time when known.
- Backfills cannot overwrite raw records without retaining the old checksum and replacement reason.
- Backtests must pin provider versions, query parameters, and dataset snapshots.

## Phase 0 Non-Goals

- No direct live trading integration.
- No custody, deposits, withdrawals, transfers, margin, futures, or leverage.
- No paid-provider lock-in as a core requirement.
- No synthetic data as the default runtime source.
