from __future__ import annotations

from typing import Any

import pandas as pd
import requests

PUBLIC_BASE_URL = "https://fapi.binance.com"


def _request_klines(params: dict[str, Any], timeout: int = 10, base_url: str = PUBLIC_BASE_URL) -> pd.DataFrame:
    response = requests.get(f"{base_url}/fapi/v1/klines", params=params, timeout=timeout)
    response.raise_for_status()
    data = response.json()
    columns = [
        "open_time",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "close_time",
        "quote_asset_volume",
        "number_of_trades",
        "taker_buy_base_volume",
        "taker_buy_quote_volume",
        "ignore",
    ]
    return pd.DataFrame(data, columns=columns)


def get_historical_klines(
    symbol: str,
    interval: str,
    start_time: int | None = None,
    end_time: int | None = None,
    limit: int = 1000,
    base_url: str = PUBLIC_BASE_URL,
) -> pd.DataFrame:
    params: dict[str, Any] = {"symbol": symbol.upper(), "interval": interval, "limit": max(1, min(int(limit), 1500))}
    if start_time is not None:
        params["startTime"] = start_time
    if end_time is not None:
        params["endTime"] = end_time
    return _request_klines(params, base_url=base_url)


def get_latest_klines(symbol: str, interval: str, limit: int = 200, base_url: str = PUBLIC_BASE_URL) -> pd.DataFrame:
    safe_limit = max(1, min(int(limit), 1500))
    return _request_klines({"symbol": symbol.upper(), "interval": interval, "limit": safe_limit}, base_url=base_url)


def get_exchange_info(base_url: str = PUBLIC_BASE_URL, timeout: int = 10) -> dict[str, Any]:
    response = requests.get(f"{base_url}/fapi/v1/exchangeInfo", timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or not isinstance(payload.get("symbols"), list):
        raise ValueError("Malformed Binance exchangeInfo response")
    return payload


def get_server_time(base_url: str = PUBLIC_BASE_URL, timeout: int = 10) -> dict[str, Any]:
    response = requests.get(f"{base_url}/fapi/v1/time", timeout=timeout)
    response.raise_for_status()
    return response.json()


def save_klines_csv(df: pd.DataFrame, path: str) -> str:
    for column in ["open", "high", "low", "close", "volume"]:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")
    from pathlib import Path

    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output, index=False)
    return str(output)
