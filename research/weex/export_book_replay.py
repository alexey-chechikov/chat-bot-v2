"""Конечная выгрузка публичной записи стакана WEEX v2 для GPT (спецификация docs/WEEX_PUBLIC_REPLAY_EXPORT_2026-10-18.md).

Копирует ЦЕЛЫЕ файлы depth/trades2/events за указанные UTC-дни (без фильтрации по времени) в staging, считает SHA256 и
строки, пишет manifest.json и упаковывает в tar.xz. Ничего из счёта/учёта/ключей не берёт — только state/weex_book/*v2.

    .venv/bin/python3 research/weex/export_book_replay.py <staging_dir> 20261015 20261016 20261017 20261018
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "state" / "weex_book"
SYMS = ("BTCUSDT", "ETHUSDT")
KINDS = ("depth", "trades2", "events")


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for ch in iter(lambda: f.read(1 << 20), b""):
            h.update(ch)
    return h.hexdigest()


def rows(p: Path) -> int:
    with open(p, "rb") as f:
        return max(sum(1 for _ in f) - 1, 0)


def main() -> int:
    stage = Path(sys.argv[1])
    days = sys.argv[2:]
    out = stage / "weex_book_v2"
    out.mkdir(parents=True, exist_ok=True)
    files = []
    for sym in SYMS:
        for day in days:
            for kind in KINDS:
                p = SRC / f"{sym}_{day}_{kind}.csv"
                if not p.exists():
                    files.append({"file": p.name, "missing": True})
                    continue
                dst = out / p.name
                shutil.copy2(p, dst)                            # снимок на момент выгрузки (файл дня может дописываться)
                files.append({"file": p.name, "symbol": sym, "utc_day": day, "kind": kind,
                              "bytes": dst.stat().st_size, "rows": rows(dst), "sha256": sha(dst)})
    commit = subprocess.run(["git", "-C", str(ROOT), "log", "-1", "--format=%H",
                             "--", "services/weex_book/recorder.py"], capture_output=True, text=True).stdout.strip()
    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "services/weex_book/recorder.py — публичный WEEX WS, без ключей",
        "recorder_commit": commit,
        "endpoint": "wss://ws-contract.weex.com/v3/ws/public",
        "channels": ["<SYM>@depth15 (снимок при подписке, далее дельты)", "<SYM>@trade"],
        "files_whole_utc_days": days,
        "note_last_day": "файл последнего дня скопирован целиком на момент created_utc (запись продолжалась)",
        "timestamps": {"E": "время события биржи, мс epoch", "T": "время сделки биржи, мс epoch",
                       "recv_ms": "часы мака при получении, мс epoch (macOS NTP; погрешность не измерялась)",
                       "U/u": "первый/последний update id дельты стакана (как пришли)"},
        "fields": {"depth.csv": "kind,U,u,E,recv_ms,session,applied,b,a — b/a исходные JSON уровни (до 15), applied=0 "
                                "— дельта не применена к книге (gap до ресинка)",
                   "trades2.csv": "t,T,E,recv_ms,session,p,q,m_raw — m_raw как пришло (buyer-is-maker: true = агрессор "
                                  "продавец; договор источника — по документации WEEX, не проверен отдельно)",
                   "events.csv": "recv_ms,session,event,detail — connect/snapshot/gap/resync/disconnect"},
        "units": {"price": "USDT", "quantity": "в монете контракта (BTC, ETH) — как в потоке; множитель не применялся"},
        "contract_specs_on_export_day": {"BTCUSDT": {"tick": 0.1, "qty_step": 0.0001},
                                         "ETHUSDT": {"tick": 0.01, "qty_step": 0.001},
                                         "source": "конфиги сеток bot7 (state/weex_grid*_config.json), не exchangeInfo"},
        "coverage": "см. events.csv каждого дня и docs/WEEX_BOOK_INVENTORY_2026-10-18.json; пропуски не заполнялись",
        "excluded": "приватные ордера, ответы аккаунта, ключи, env, балансы, state/config ботов, legacy _book/_trades",
        "files": files,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    tar_path = stage / f"weex_book_v2_{days[0]}_{days[-1]}.tar"
    with tarfile.open(tar_path, "w") as tf:
        tf.add(out, arcname="weex_book_v2")
    subprocess.run(["xz", "-T0", "-6", "-f", str(tar_path)], check=True)
    xz = Path(str(tar_path) + ".xz")
    print(json.dumps({"archive": str(xz), "bytes": xz.stat().st_size, "sha256": sha(xz),
                      "files": len([f for f in files if not f.get("missing")]),
                      "missing": [f["file"] for f in files if f.get("missing")]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
