from __future__ import annotations


CONTRACT_UNIVERSE_NAME = "crypto13_contract_v1"

CONTRACT_UNIVERSE: tuple[str, ...] = (
    "BTCUSDT",
    "ETHUSDT",
    "BNBUSDT",
    "SOLUSDT",
    "XRPUSDT",
    "ADAUSDT",
    "DOGEUSDT",
    "TRXUSDT",
    "AVAXUSDT",
    "LINKUSDT",
    "DOTUSDT",
    "LTCUSDT",
    "ATOMUSDT",
    "BCHUSDT",
    "ETCUSDT",
    "XLMUSDT",
    "ARBUSDT",
    "OPUSDT",
    "MATICUSDT",
    "POLUSDT",
    "APTUSDT",
    "SUIUSDT",
    "NEARUSDT",
    "INJUSDT",
    "UNIUSDT",
    "AAVEUSDT",
    "CRVUSDT",
    "SNXUSDT",
    "DYDXUSDT",
    "GMXUSDT",
    "RNDRUSDT",
    "FETUSDT",
    "AGIXUSDT",
    "GRTUSDT",
    "FILUSDT",
    "ICPUSDT",
    "IMXUSDT",
    "STXUSDT",
    "RUNEUSDT",
    "KASUSDT",
    "ORDIUSDT",
    "TIAUSDT",
    "SEIUSDT",
    "FTMUSDT",
    "ENAUSDT",
    "JUPUSDT",
)


def configured_universe() -> list[str]:
    return list(CONTRACT_UNIVERSE)
