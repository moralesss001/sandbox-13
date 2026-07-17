from pathlib import Path

import yaml

from src.main import _build_parser
from src.universe import CONTRACT_UNIVERSE, CONTRACT_UNIVERSE_NAME, configured_universe


EXPECTED_CONTRACT_UNIVERSE = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT",
    "DOGEUSDT", "TRXUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT", "LTCUSDT",
    "ATOMUSDT", "BCHUSDT", "ETCUSDT", "XLMUSDT", "ARBUSDT", "OPUSDT",
    "MATICUSDT", "POLUSDT", "APTUSDT", "SUIUSDT", "NEARUSDT", "INJUSDT",
    "UNIUSDT", "AAVEUSDT", "CRVUSDT", "SNXUSDT", "DYDXUSDT", "GMXUSDT",
    "RNDRUSDT", "FETUSDT", "AGIXUSDT", "GRTUSDT", "FILUSDT", "ICPUSDT",
    "IMXUSDT", "STXUSDT", "RUNEUSDT", "KASUSDT", "ORDIUSDT", "TIAUSDT",
    "SEIUSDT", "FTMUSDT", "ENAUSDT", "JUPUSDT",
]


def test_contract_universe_matches_owner_contract_exactly():
    assert len(CONTRACT_UNIVERSE) == 46
    assert len(set(CONTRACT_UNIVERSE)) == 46
    assert list(CONTRACT_UNIVERSE) == EXPECTED_CONTRACT_UNIVERSE


def test_configured_universe_returns_an_independent_contract_copy():
    first = configured_universe()
    first.pop()

    assert configured_universe() == EXPECTED_CONTRACT_UNIVERSE


def test_yaml_selects_contract_source_without_a_second_symbol_list():
    config = yaml.safe_load(Path("config/research_config.yaml").read_text(encoding="utf-8"))

    assert config["live_research"]["universe"] == CONTRACT_UNIVERSE_NAME
    assert "symbols" not in config["live_research"]


def test_direct_live_research_cli_defaults_to_contract_universe():
    args = _build_parser().parse_args(["live-research"])

    assert args.symbols.split(",") == EXPECTED_CONTRACT_UNIVERSE
