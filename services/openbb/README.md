# OpenBB sidecar

Standalone process that serves the [OpenBB Platform](https://github.com/OpenBB-finance/OpenBB) HTTP API on `http://localhost:6900`. The uteki backend (`services/api/`) talks to it over plain HTTP; nothing in this directory is imported by the backend.

## Why a sidecar

OpenBB is **AGPL-3.0-only**. Linking the SDK into the uteki backend would force AGPL on the whole hosted service (network use clause). Running it as a separate process — uteki → HTTP → OpenBB — keeps the licenses cleanly separated.

## Providers installed

| Provider | What it gives uteki |
|---|---|
| `openbb-fred` | FRED economic series — rates, CPI, yield curve, SOFR (free key). |
| `openbb-federal-reserve` | FOMC + Fed treasury rates (no key). |
| `openbb-ecb` | ECB reference rates + EU rates (no key). |
| `openbb-fmp` | Earnings calendar, analyst estimates, price targets, insider trading, institutional + ETF holdings (free key tier). |
| `openbb-sec` | EDGAR-backed income/balance/cash_flow + 13F + insider + MD&A (no key). |

## Run

```bash
cd services/openbb
uv sync
uv run openbb-api --host 127.0.0.1 --port 6900 --no-reload
```

API keys live in `~/.openbb_platform/user_settings.json` (created automatically on first run; see OpenBB docs for `credentials.fred_api_key`, `credentials.fmp_api_key`).

Probe:

```bash
curl 'http://localhost:6900/api/v1/economy/fred_series?symbol=DGS10&limit=5'
```
