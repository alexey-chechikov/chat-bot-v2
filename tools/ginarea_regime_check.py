"""Сетка по режиму SMA100 на движке GinArea (11.10, оператор: «бэктесты для чего? у тебя джинерия»).

Правило из research/weex/regime_grid.py: режим дня = вчерашнее закрытие BTC выше/ниже SMA100 → лонг-сетка / шорт-
сетка; на смене режима сторона закрывается (тест GinArea на отрезке кончается открытой позицией — итог
current_profit включает мешок по цене конца отрезка, т.е. закрытие без комиссии выхода).
Каждый отрезок режима с 25.09.2025 (начало истории тестов GinArea) гоняется ДВАЖДЫ: по режиму и наоборот
(та же сетка, противоположная сторона) — разница = польза направления на независимом движке.
Сетка: шаг 0.6, цель 1.4, 50 ордеров, 0.001 BTC, выход по каждому ордеру (obap выкл), без множителя объёма.
Бот — шорт-клон 4568400511 (разрешён к тестам 01.10); параметры возвращаются в конце.

    .venv/bin/python3 tools/ginarea_regime_check.py            # прогон 0.6/1.4
    .venv/bin/python3 tools/ginarea_regime_check.py --gs=0.4 --tog=1.4 --spec="gs=0.4,maxOp=50,..." --out=state/x.jsonl
    .venv/bin/python3 tools/ginarea_regime_check.py --restore  # вернуть параметры бота

Пропуск уже посчитанного (ревью GPT 13.10 §6: ключ из ДАТ давал одинаковый ключ концам 08:00 и 12:00 одного дня, а
смена maxOp/объёма/Dynamic молча брала старый результат) — по ключу (символ, начало и конец отрезка UTC в мс, сторона,
sha256 полного ЭФФЕКТИВНОГО конфига, который ставится боту, sha256 закрытий дней, задающих режим отрезка). Всё это
пишется в каждую запись вместе с самим конфигом; записи без этих полей (до 13.10) не переиспользуются. После установки
значимые параметры (сторона, шаг, цель, maxOp, объём, obap, so, ioo) сверяются с ответом GinArea — расхождение = стоп.
SPEC накладывается на полный конфиг клона: не заданные в нём so/ioo (смещения Dynamic) НАСЛЕДУЮТСЯ — они печатаются
и пишутся в запись, ненулевые — предупреждение (чтобы исключить, задать so=0,ioo=0 в --spec явно).
Режим считается только по ПОЛНЫМ дням frozen (1440 минут), неполный день внутри истории — отказ.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import ginarea_target_sweep as gts  # noqa: E402

def _opt(name: str, default: str) -> str:
    return next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith(f"--{name}=")), default)


BOT = 4568400511                                          # BTC-клон: отрезки и бот — только BTC (ETH — target_sweep)
SYMBOL = "BTCUSDT"
SRC = ROOT / "backtests" / "frozen" / f"{SYMBOL}_1m_2y.csv"
OUT = ROOT / _opt("out", "state/ginarea_regime_check.jsonl")
GS, TOG = float(_opt("gs", "0.6")), float(_opt("tog", "1.4"))
SPEC = _opt("spec", f"gs={GS},maxOp=50,q.minQ=0.001,q.maxQ=null,q.qr=null,obap=0")
if not SPEC.strip():                                      # пустой --spec = базовые параметры клона (maxOp 400, qr…)
    sys.exit("--spec пустой — не передавать или задать полностью")
DAY_MS = 86_400_000
SIGNIFICANT = ("side", "gs", "gap.tog", "maxOp", "q.minQ", "q.maxQ", "q.qr", "obap", "so", "ioo")
KEY_FIELDS = ("symbol", "from_ms", "to_ms", "side", "config_sha256", "data_sha256")


def daily_closes():
    """Закрытия ПОЛНЫХ UTC-дней (1440 минут, закрытие минуты 23:59) по всем календарным дням; неполный — NaN."""
    import numpy as np
    import pandas as pd
    d = pd.read_csv(SRC, usecols=["ts", "close"])
    ms = d["ts"].to_numpy(dtype=np.int64)
    if (ms % 60_000).any() or (np.diff(ms) <= 0).any():
        raise SystemExit(f"{SRC.name}: метки не на минутной сетке или с дублями — отказ")
    day = ms // DAY_MS
    days, first, cnt = np.unique(day, return_index=True, return_counts=True)
    full = cnt == 1440
    vals = np.full(days[-1] - days[0] + 1, np.nan)
    vals[days[full] - days[0]] = d["close"].to_numpy(dtype=float)[(first + cnt - 1)[full]]
    idx = pd.to_datetime((np.arange(days[0], days[-1] + 1) * DAY_MS), unit="ms", utc=True)
    return pd.Series(vals, index=idx)


def segments(dc=None):
    import pandas as pd
    if dc is None:
        dc = daily_closes()
    sma = dc.rolling(100).mean()
    reg = (dc > sma).where(sma.notna() & dc.notna()).shift(1)     # режим дня d+1 — по закрытию дня d
    reg = reg[reg.index >= "2025-09-25"]
    if reg.isna().any():
        raise SystemExit("режим с пропусками (неполные дни frozen) — отказ")
    grp = reg.ne(reg.shift()).cumsum()
    now = datetime.now(timezone.utc) - timedelta(minutes=30)
    out = []
    for _, g in reg.groupby(grp):
        a = g.index[0].to_pydatetime()
        b = min((g.index[-1] + pd.Timedelta("1D")).to_pydatetime(), now)
        out.append((bool(g.iloc[0]), a, b))
    return out


def _ms(t: datetime) -> int:
    return int(round(t.timestamp() * 1000))


def data_sha256(dc, a: datetime, b: datetime) -> str:
    """sha256 закрытий дней, задающих режим отрезка [a, b): с a−101 дня (SMA100 дня до a) по день перед b."""
    import pandas as pd
    lo = pd.Timestamp(a) - pd.Timedelta(days=101)
    w = dc[(dc.index >= lo) & (dc.index < pd.Timestamp(b))]
    rows = [[int(t.value // 1_000_000), None if pd.isna(v) else repr(float(v))] for t, v in w.items()]
    return hashlib.sha256(json.dumps(rows, separators=(",", ":")).encode()).hexdigest()


def config_sha256(cfg: dict) -> str:
    return hashlib.sha256(json.dumps(cfg, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def effective(work, side: int):
    """Параметры стороны (их передаём в gts.set_config) и полный конфиг, который реально ставится боту: шаг и цель
    set_config накладывает поверх — здесь так же."""
    from services.ginarea_api.models import DefaultGridParams, Side
    d = work.to_dict()
    d["side"] = side
    d["s"] = side                                          # у односторонних ботов s = сторона
    p = DefaultGridParams.from_dict(d)
    if p.side is not None and not isinstance(p.side, Side):
        p = dataclasses.replace(p, side=Side(int(p.side)))
    eff = dataclasses.replace(p, gs=GS, gap=dataclasses.replace(p.gap, tog=TOG))
    return p, eff.to_dict()


def _pick(cfg: dict, key: str):
    outer, _, inner = key.partition(".")
    v = cfg.get(outer)
    return (v or {}).get(inner) if inner else v


def _same(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, bool) or isinstance(b, bool):
        return bool(a) == bool(b)
    try:
        return abs(float(a) - float(b)) <= 1e-9
    except (TypeError, ValueError):
        return a == b


def readback_diff(want: dict, got: dict) -> list[str]:
    return [f"{k}: {_pick(want, k)!r} → {_pick(got, k)!r}" for k in SIGNIFICANT
            if not _same(_pick(want, k), _pick(got, k))]


def skip_key(rec: dict):
    """Ключ записи или None (старая запись без точных концов/хешей — не переиспользуется)."""
    if rec.get("current_profit") is None or any(rec.get(k) in (None, "") for k in KEY_FIELDS):
        return None
    return (rec["symbol"], int(rec["from_ms"]), int(rec["to_ms"]), int(rec["side"]),
            rec["config_sha256"], rec["data_sha256"])


def load_done(path: Path) -> tuple[set, int]:
    done, old = set(), 0
    if path.exists():
        for ln in path.read_text(encoding="utf-8").splitlines():
            k = skip_key(json.loads(ln))
            if k is None:
                old += 1
            else:
                done.add(k)
    return done, old


def _nonzero(v) -> bool:
    try:
        return v is not None and float(v) != 0.0
    except (TypeError, ValueError):
        return True


def main() -> None:
    api, bt = gts._api([BOT])
    base = gts._base(api, BOT)
    if "--restore" in sys.argv:
        api.set_params(BOT, base)
        print("параметры возвращены")
        return
    done, old = load_done(OUT)
    if old:
        print(f"записей без точного ключа (старые/неудачные): {old} — не переиспользуются", flush=True)
    work = gts.apply_set(base, SPEC)
    wd = work.to_dict()                                    # полный конфиг: so/ioo могут жить и в extra_raw
    so, ioo = wd.get("so"), wd.get("ioo")
    print(f"эффективные смещения Dynamic: so={so} ioo={ioo}", flush=True)
    if _nonzero(so) or _nonzero(ioo):
        in_spec = {it.split("=", 1)[0].strip() for it in SPEC.split(",") if "=" in it}
        how = "заданы в --spec" if in_spec & {"so", "ioo"} else "унаследованы от клона (SPEC их не задаёт)"
        print(f"ВНИМАНИЕ: so={so}, ioo={ioo} {how} — отрезки считаются С этими смещениями; "
              f"исключить — so=0,ioo=0 в --spec", flush=True)
    dc = daily_closes()
    try:
        for long_regime, a, b in segments(dc):
            dh = data_sha256(dc, a, b)
            for mode in ("режим", "наоборот"):
                side = 1 if (long_regime == (mode == "режим")) else 2
                p, cfg = effective(work, side)
                ch = config_sha256(cfg)
                if (SYMBOL, _ms(a), _ms(b), side, ch, dh) in done:
                    continue
                gts.set_config(api, BOT, p, GS, TOG)
                got = api.get_params(BOT)
                if int(got.side or 0) != side:
                    raise SystemExit(f"сторона не встала: {got.side} вместо {side}")
                diff = readback_diff(cfg, got.to_dict())
                if diff:
                    raise SystemExit(f"параметры не встали на {BOT}: {'; '.join(diff)}")
                gts.clear_slot(bt, BOT)
                meta = {"symbol": SYMBOL, "from_ms": _ms(a), "to_ms": _ms(b), "config_sha256": ch,
                        "data_sha256": dh, "so": cfg.get("so"), "ioo": cfg.get("ioo"), "config": cfg,
                        "readback_sha256": config_sha256(got.to_dict())}
                r = gts.run_one(bt, BOT, GS, TOG, a, b, OUT, extra=meta)
                print(f"{'ЛОНГ' if long_regime else 'ШОРТ'}-режим {a:%Y-%m-%d %H:%M}→{b:%Y-%m-%d %H:%M} UTC [{mode}, "
                      f"сторона {'лонг' if side == 1 else 'шорт'}]: итог {r['current_profit']} закрыто {r['profit']} "
                      f"оборот {r['volume']} худший итог {r['worst_total']} ({r['seconds']}с)", flush=True)
                time.sleep(gts.PAUSE)
    finally:
        api.set_params(BOT, base)
        print("параметры бота возвращены", flush=True)


if __name__ == "__main__":
    main()
