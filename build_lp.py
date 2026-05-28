#!/usr/bin/env python3
"""Fetch LP token prices from DeFiLlama and rebuild the LP index dashboard HTML."""

import json
import os
import time
import urllib.request
from datetime import datetime, timezone

OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "lp_dashboard_standalone.html")

TOKENS = {
    "JLP": "coingecko:jupiter-perpetuals-liquidity-provider-token",
    "GM-BTC-USDC": "arbitrum:0x47c031236e19d024b42f8AE6780E44A573170703",
    "GM-ETH-USDC": "arbitrum:0x70d95587d40A2caf56bd97485aB3Eec10Bee6336",
    "GLV-BTC-USDC": "arbitrum:0xdF03EEd325b82bC1d4Db8b49c30ecc9E05104b96",
    "GLV-ETH-USDC": "arbitrum:0x528A5bac7E746C9A509A1f4F6dF58A03d44279F9",
    # Benchmarks
    "BTC": "coingecko:bitcoin",
    "ETH": "coingecko:ethereum",
    "SPYX": "coingecko:spx6900",
}

PORTFOLIOS = {
    "50/50 BTC/USDC": [("BTC", 0.5), ("USDC", 0.5)],
    "50/50 ETH/USDC": [("ETH", 0.5), ("USDC", 0.5)],
}

LOOKBACK_DAYS = 60
CHUNK_SIZE = 45


def fetch_prices(defillama_ids, from_ts, to_ts):
    """Fetch batchHistorical prices from DeFiLlama. Returns {id: {date: price}}."""
    timestamps = list(range(from_ts, to_ts + 86400, 86400))
    result = {tid: {} for tid in defillama_ids}

    for ts_start in range(0, len(timestamps), CHUNK_SIZE):
        ts_chunk = timestamps[ts_start:ts_start + CHUNK_SIZE]
        for i in range(0, len(defillama_ids), 2):
            batch = defillama_ids[i:i + 2]
            coins_param = json.dumps({tid: ts_chunk for tid in batch})
            encoded = urllib.parse.quote(coins_param, safe='')
            url = f"https://coins.llama.fi/batchHistorical?coins={encoded}&searchWidth=4h"
            for attempt in range(3):
                try:
                    with urllib.request.urlopen(url, timeout=30) as resp:
                        data = json.loads(resp.read())
                    for tid, coin in data.get("coins", {}).items():
                        for entry in coin.get("prices", []):
                            date_str = datetime.fromtimestamp(entry["timestamp"], tz=timezone.utc).strftime("%Y-%m-%d")
                            result[tid][date_str] = entry["price"]
                    break
                except Exception as e:
                    if attempt < 2:
                        time.sleep(2)
                    else:
                        print(f"    Error fetching {batch}: {e}")
            time.sleep(0.5)
    return result


def compute_portfolios(prices_by_symbol, symbols):
    """Compute 50/50 portfolio values. USDC = $1.00."""
    result = {}
    for name, components in PORTFOLIOS.items():
        series = []
        # Get union of dates across all components
        all_dates = set()
        for sym, _ in components:
            if sym == "USDC":
                continue
            all_dates.update(prices_by_symbol.get(sym, {}).keys())
        for date_str in sorted(all_dates):
            val = 0.0
            ok = True
            for sym, weight in components:
                if sym == "USDC":
                    val += weight * 1.0
                elif date_str in prices_by_symbol.get(sym, {}):
                    val += weight * prices_by_symbol[sym][date_str]
                else:
                    ok = False
                    break
            if ok:
                series.append([date_str, round(val, 8)])
        result[name] = series
    return result


def main():
    print("Fetching LP token prices from DeFiLlama...")
    to_ts = int(datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
    from_ts = to_ts - LOOKBACK_DAYS * 86400

    all_ids = list(TOKENS.values())
    prices_raw = fetch_prices(all_ids, from_ts, to_ts)

    # Map defillama_id → symbol
    id_to_symbol = {v: k for k, v in TOKENS.items()}
    prices_by_symbol = {}
    for did, dates in prices_raw.items():
        sym = id_to_symbol.get(did, did)
        series = sorted([[d, round(p, 12)] for d, p in dates.items()])
        prices_by_symbol[sym] = {d: p for d, p in series}

    # Build series for dashboard
    all_data = {}
    for sym in TOKENS:
        if sym in prices_by_symbol:
            series = [[d, p] for d, p in sorted(prices_by_symbol[sym].items())]
            if series:
                all_data[sym] = series
                print(f"  {sym}: {len(series)} pts | {series[0][0]} → {series[-1][0]} | ${series[-1][1]:.4f}")

    # Compute portfolios
    portfolios = compute_portfolios(prices_by_symbol, TOKENS)
    for name, series in portfolios.items():
        all_data[name] = series
        print(f"  {name}: {len(series)} pts | ${series[-1][1]:.4f}")

    # SPYX benchmark
    if "SPYX" in all_data and len(all_data["SPYX"]) > 1:
        spx = all_data["SPYX"]
        base = spx[0][1]
        all_data["SPYX"] = [[d, (p / base) * 100] for d, p in spx]
        print(f"  SPYX: normalized to base 100, {len(all_data['SPYX'])} pts")

    with open(OUTPUT_FILE) as f:
        template = f.read()

    data_line_start = "var ALL_DATA = "
    data_line_end = ";\n\nvar LP_TOKENS = ["
    start_idx = template.index(data_line_start)
    end_idx = template.index(data_line_end, start_idx)

    new_data = f"var ALL_DATA = {json.dumps(all_data)}"
    new_html = template[:start_idx] + new_data + template[end_idx:]

    # Inject refresh timestamp
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    new_html = new_html.replace("REFRESH_TIMESTAMP", ts)

    with open(OUTPUT_FILE, "w") as f:
        f.write(new_html)

    total = sum(len(v) for v in all_data.values())
    print(f"\nDone! {len(new_html):,} bytes, {total} total data points.")


if __name__ == "__main__":
    main()
