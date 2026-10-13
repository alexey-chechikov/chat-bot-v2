"""Сырой журнал ликвидаций (P0 13.10, ТЗ ATLAS §3): время биржи, сторона ликвидированной позиции, единицы и
основа цены сохраняются; CSV не меняется. Сообщения — по документированным схемам Bybit allLiquidation (T,s,S,v,p),
Binance forceOrder (o.T,s,S,q,p,ap), OKX liquidation-orders (details: side, sz, bkPx, ts)."""
import json

from market_collector import liquidations as lq


def test_import_and_raw_dir_defined():
    assert lq.RAW_DIR.name == "liq_raw"                 # модуль импортируется (MARKET_LIVE_DIR есть)


def test_bybit_documented_payload_raw(tmp_path, monkeypatch):
    monkeypatch.setattr(lq, "RAW_DIR", tmp_path)
    liq = {"T": 1740000000000, "s": "BTCUSDT", "S": "Buy", "v": "0.01", "p": "83000"}
    side = "short" if str(liq["S"]).lower() == "sell" else "long"   # та же формула, что в живом потоке
    assert side == "long"                               # S=Buy — ликвидирован ЛОНГ (документация Bybit)
    lq._write_raw(lq.raw_record("bybit", "BTCUSDT", side, liq, exchange_ts_ms=liq["T"], qty=liq["v"],
                                qty_unit="base", price=liq["p"], price_basis="bankruptcy"))
    rec = json.loads(next(tmp_path.glob("bybit_*.jsonl")).read_text().splitlines()[0])
    assert rec["exchange_ts_ms"] == 1740000000000 and rec["recv_ms"] > 0
    assert rec["side_liquidated"] == "long" and rec["price_basis"] == "bankruptcy" and rec["raw"]["S"] == "Buy"


def test_okx_contract_normalization_and_spec(tmp_path, monkeypatch):
    monkeypatch.setattr(lq, "RAW_DIR", tmp_path)
    d = {"side": "sell", "sz": "3", "bkPx": "83000", "ts": "1740000000123", "instId": "BTC-USDT-SWAP"}
    qty = float(d["sz"]) * lq.OKX_CONTRACT_SIZE["BTC-USDT-SWAP"]
    assert abs(qty - 0.03) < 1e-12                      # 3 контракта × ctVal 0.01 BTC, не sz × цена
    lq._write_raw(lq.raw_record("okx", "BTCUSDT", "long", d, exchange_ts_ms=d["ts"], qty=f"{qty:.6f}",
                                qty_unit="base (sz × ctVal)", price=d["bkPx"], price_basis="bankruptcy",
                                extra={"ctVal": 0.01, "spec": lq.OKX_SPEC_VERSION}))
    rec = json.loads(next(tmp_path.glob("okx_*.jsonl")).read_text().splitlines()[0])
    assert rec["exchange_ts_ms"] == 1740000000123 and rec["ctVal"] == 0.01 and "2026-10-13" in rec["spec"]


def test_missing_exchange_time_is_none_not_zero(tmp_path, monkeypatch):
    monkeypatch.setattr(lq, "RAW_DIR", tmp_path)
    rec = lq.raw_record("bybit", "BTCUSDT", "long", {}, exchange_ts_ms=None, qty="", qty_unit="base", price="",
                        price_basis="bankruptcy")
    assert rec["exchange_ts_ms"] is None                # неполнота не заменяется нулём


def test_raw_write_failure_does_not_raise(monkeypatch):
    monkeypatch.setattr(lq, "RAW_DIR", lq.Path("/dev/null/nope"))
    lq._write_raw({"exchange": "bybit"})                # ошибка только в лог — основной поток жив
