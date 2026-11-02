"""Обёртка ядра gridk.c (ctypes). Компилируется в scratchpad при первом вызове (cc -O2), кэш по sha исходника.
Издержки по умолчанию — живые WEEX (CLAUDE.md): мейкер 0.016% на вход и тейк (POST_ONLY), выход по рынку тейкер
0.048% + проскальзывание 0.02%; возвратов комиссии нет (с 20.10 — ноль)."""
from __future__ import annotations

import ctypes
import hashlib
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
SCR = Path("/private/tmp/claude-501/-Users-alexeychechikov/85655d8a-c366-454b-bd04-314adf4588cf/scratchpad/mr")
MAKER, TAKER, SLIP = 0.00016, 0.00048, 0.0002
COLS = ["net", "tp_gross", "fees", "funding", "exit_pnl", "bag", "dd", "fills", "tps", "lots_exit", "end", "peak_cost",
        "exit_fee"]
K = len(COLS)
_LIB = None


def lib():
    global _LIB
    if _LIB is None:
        src = HERE / "gridk.c"
        h = hashlib.sha256(src.read_bytes()).hexdigest()[:12]
        so = SCR / f"gridk_{h}.so"
        if not so.exists():
            subprocess.run(["cc", "-O2", "-shared", "-fPIC", "-o", str(so), str(src)], check=True)
        L = ctypes.CDLL(str(so))
        dp, lp, ip = (np.ctypeslib.ndpointer(t, flags="C_CONTIGUOUS") for t in (np.float64, np.int64, np.int32))
        L.batch.argtypes = [dp, dp, dp, dp, ctypes.c_long, lp, lp, lp, ip, dp, ctypes.c_long, ctypes.c_int,
                            ctypes.c_double, ctypes.c_double, ctypes.c_double, ctypes.c_double, ctypes.c_double,
                            ctypes.c_int, ctypes.c_double, ctypes.c_double, ctypes.c_double, dp]
        L.batch.restype = None
        _LIB = L
    return _LIB


class Market:
    """Минуты: ts (сек), path4, open, close, фандинг по минутам (ставка на минуте расчёта, иначе 0)."""

    def __init__(self, ts, o, h, l, c, fund: pd.Series | None = None):
        self.ts = np.ascontiguousarray(ts, dtype=np.int64)
        self.o = np.ascontiguousarray(o, dtype=float)
        self.c = np.ascontiguousarray(c, dtype=float)
        up = self.c >= self.o
        p = np.empty((len(o), 4))
        p[:, 0], p[:, 1], p[:, 2], p[:, 3] = o, np.where(up, l, h), np.where(up, h, l), c
        self.pts = np.ascontiguousarray(p.ravel())
        self.fund = np.zeros(len(o))
        if fund is not None:
            idx = np.searchsorted(self.ts, fund.index.to_numpy())
            ok = (idx < len(self.ts)) & (self.ts[np.minimum(idx, len(self.ts) - 1)] == fund.index.to_numpy())
            self.fund[idx[ok]] = fund.to_numpy()[ok]
        self.n = len(o)

    def idx(self, t_sec) -> np.ndarray:
        """Первая минута с ts ≥ t (для остановок биржи — первая торговая минута после)."""
        return np.searchsorted(self.ts, np.asarray(t_sec, dtype=np.int64), side="left")

    def run(self, i0, i1, side, i_off=None, step=0.6, tgt=1.4, order_usd=100.0, qty=0.0, cap=6000.0,
            max_lots=60, plus=False, mk=MAKER, tk=TAKER, sl=SLIP, lim=None) -> np.ndarray:
        """lim — граница зоны входа на эпизод: лонг входит только по уровню ≤ lim, шорт — ≥ lim (None — без)."""
        i0 = np.ascontiguousarray(np.atleast_1d(i0), dtype=np.int64)
        i1 = np.ascontiguousarray(np.atleast_1d(i1), dtype=np.int64)
        io = i1 if i_off is None else np.ascontiguousarray(np.atleast_1d(i_off), dtype=np.int64)
        sd = np.ascontiguousarray(np.broadcast_to(np.atleast_1d(side), i0.shape), dtype=np.int32)
        if lim is None:
            lm = np.where(sd > 0, np.inf, -np.inf)
        else:
            lm = np.where(np.isnan(lim), np.where(sd > 0, np.inf, -np.inf), lim)
        lm = np.ascontiguousarray(np.broadcast_to(lm, i0.shape), dtype=float)
        out = np.zeros(len(i0) * K)
        lib().batch(self.pts, self.o, self.c, self.fund, self.n, i0, io, i1, sd, lm, len(i0), int(plus),
                    step, tgt, order_usd, qty, cap, max_lots, mk, tk, sl, out)
        return out.reshape(len(i0), K)
