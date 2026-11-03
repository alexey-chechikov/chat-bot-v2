"""Ретест голубой H4 (правило GPT slow_rejection, 49194bb): повтор на 04–10.2026 и проверка вне выборки. Правила — PREREG.md.
Запуск: check.py --pk-btc=<bars_*.pkl BTC из mr_data.build>   (nice 20)."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "research" / "tv_lab_1025"))
import strategies as S  # noqa: E402

TS = lambda s: int(pd.Timestamp(s, tz="UTC").timestamp())  # noqa: E731
H, H4S = 3600, 14400
COST = 0.00048 + 0.0002
WIN = {"R 04–10.2026 (повтор)": ("2026-04-01", "2026-11-01"), "P 05.2024–03.2026": ("2024-05-15", "2026-04-01"),
       "O 2018–05.2024": ("2018-01-01", "2024-05-15")}
EXITS = {"S стоп или 80 ч": "S", "T полный 2R": "T", "E2 стоп + два H4 за EMA": "E2", "H половина 2R": "H"}
RNG = np.random.default_rng(20261103)


class M:
    def __init__(self, pk: Path, minute_order: bool):
        m, h1, h4, d1, fund = pd.read_pickle(pk)
        print(f"кэш {pk.name}: sha256 {hashlib.sha256(pk.read_bytes()).hexdigest()[:16]}…; H1 {len(h1)}, H4 {len(h4)}, "
              f"до {pd.to_datetime(h1.index[-1], unit='s')}", flush=True)
        self.mo = minute_order
        self.mt = m["ts"].to_numpy()
        self.ml, self.mh = m["low"].to_numpy(), m["high"].to_numpy()
        self.t1 = h1.index.to_numpy()
        self.o1, self.h1, self.l1, self.c1 = (h1[k].to_numpy() for k in ("open", "high", "low", "close"))
        self.B1 = S.ema(self.c1, 200)
        self.t4 = h4.index.to_numpy()
        self.o4, self.h4, self.l4, self.c4 = (h4[k].to_numpy() for k in ("open", "high", "low", "close"))
        self.B4 = S.ema(self.c4, 200)
        self.atr4 = S.atr(self.h4, self.l4, self.c4, 14)
        self.sl4 = self.B4 / np.r_[np.full(6, np.nan), self.B4[:-6]] - 1
        f = fund[~fund.index.duplicated(keep="last")]
        self.ft, self.fr = f.index.to_numpy(), f.to_numpy()
        j1 = np.searchsorted(self.t1, self.t4 + H4S - H, side="left")      # H1-бар, закрывающийся вместе с H4
        ok = (j1 < len(self.t1)) & (self.t1[np.minimum(j1, len(self.t1) - 1)] == self.t4 + H4S - H)
        self.B1at4 = np.where(ok, self.B1[np.minimum(j1, len(self.t1) - 1)], np.nan)
        self.h1of = {int(t): i for i, t in enumerate(self.t1)}
        self.i4of = {int(t): i for i, t in enumerate(self.t4)}

    def signals(self):
        B, c, o, h, l = self.B4, self.c4, self.o4, self.h4, self.l4
        with np.errstate(invalid="ignore"):
            L = (l <= B * 1.01) & (c > B) & (c <= B * 1.01) & (self.B1at4 > B) & (self.sl4 >= 0) & ((c / o - 1) >= 0.002)
            Sh = (h >= B * 0.99) & (c < B) & (c >= B * 0.99) & (self.B1at4 < B) & (self.sl4 <= 0) & ((c / o - 1) <= -0.002)
        out = {}
        for side, cond in ((1, L), (-1, Sh)):
            cond = cond & np.isfinite(self.atr4) & np.isfinite(self.sl4)
            cond[:400] = False
            out[side] = cond & ~np.r_[False, cond[:-1]]
        return out

    def plan(self, side, i):
        """Сигнал на закрытии H4 i → (час входа, цена, стоп, qty) или None (вход не прошёл проверку open)."""
        if i + 1 >= len(self.t4):
            return None
        te = int(self.t4[i] + H4S)
        j = self.h1of.get(te)
        if j is None:
            return None
        px, B = self.o1[j], self.B4[i]
        if not (side * (px - B) > 0 and abs(px / B - 1) <= 0.015):
            return None
        lo = max(0, i - 5)
        stop = (min(self.l4[lo:i + 1].min(), B) - 0.25 * self.atr4[i]) if side == 1 else \
            (max(self.h4[lo:i + 1].max(), B) + 0.25 * self.atr4[i])
        risk = side * (px - stop)
        if risk <= 0:
            return None
        qty = min(3.0 / risk, 200.0 / px)
        return j, px, stop, qty

    def first_hit(self, j, side, stop, tgt):
        """В часе j касаются и стоп, и тейк: по минутам — кто первый (в одной минуте — стоп)."""
        a, b = np.searchsorted(self.mt, self.t1[j]), np.searchsorted(self.mt, self.t1[j] + H)
        lo, hi = self.ml[a:b], self.mh[a:b]
        hs = np.flatnonzero(lo <= stop) if side == 1 else np.flatnonzero(hi >= stop)
        ht = np.flatnonzero(hi >= tgt) if side == 1 else np.flatnonzero(lo <= tgt)
        if not len(ht):
            return "stop"
        if not len(hs):
            return "tgt"
        return "tgt" if ht[0] < hs[0] else "stop"

    def trade(self, side, i, ex, cost=COST):
        p = self.plan(side, i)
        if p is None:
            return None
        j0, px, stop, qty = p
        tgt = px + side * 2 * (side * (px - stop)) if ex in ("T", "H") else None
        legs, q_open, fund, both = [], qty, 0.0, 0
        n1 = len(self.t1)
        end = min(j0 + 80, n1 - 1)
        cnt = 0
        eq_path = []
        realized = 0.0
        fees = qty * px * cost
        fi = np.searchsorted(self.ft, self.t1[j0], side="right")    # расчёты строго после входа

        def settle(upto_j):
            """Расчёты фандинга ≤ open часа upto_j (расчёт на границе — до операций: выход на этом open платит)."""
            nonlocal fi, fund
            while fi < len(self.ft) and self.ft[fi] <= self.t1[upto_j]:
                fund += side * q_open * self.o1[upto_j] * self.fr[fi]
                fi += 1

        for j in range(j0, end):
            settle(j)
            hit_s = (self.l1[j] <= stop) if side == 1 else (self.h1[j] >= stop)
            hit_t = tgt is not None and ((self.h1[j] >= tgt) if side == 1 else (self.l1[j] <= tgt))
            first = "stop" if hit_s else ("tgt" if hit_t else None)
            if hit_s and hit_t:
                both += 1
                if self.mo:
                    first = self.first_hit(j, side, stop, tgt)
            if first == "tgt":
                out = max(self.o1[j], tgt) if side == 1 else min(self.o1[j], tgt)
                qq = q_open / 2 if ex == "H" else q_open
                realized += side * qq * (out - px)
                fees += qq * out * cost
                q_open -= qq
                tgt = None
                if q_open <= 1e-12:
                    return self._fin(side, i, j0, j + 1, realized, fees, fund, eq_path, both)
                if hit_s and self.mo:                 # тейк половины был первым, стоп в том же часе — остаток по стопу
                    first = "stop"
            if first == "stop":
                out = min(self.o1[j], stop) if side == 1 else max(self.o1[j], stop)
                realized += side * q_open * (out - px)
                fees += q_open * out * cost
                return self._fin(side, i, j0, j + 1, realized, fees, fund, eq_path, both)
            eq_path.append(realized + side * q_open * (self.c1[j] - px) - fees - fund)
            if ex == "E2" and (self.t1[j] + H) % H4S == 0:
                i4 = self.i4of.get(int(self.t1[j] + H - H4S))
                if i4 is not None:
                    cnt = cnt + 1 if side * (self.c4[i4] - self.B4[i4]) < 0 else 0
                    if cnt >= 2 and j + 1 < n1:
                        settle(j + 1)
                        out = self.o1[j + 1]
                        realized += side * q_open * (out - px)
                        fees += q_open * out * cost
                        return self._fin(side, i, j0, j + 1, realized, fees, fund, eq_path, both)
        settle(end)
        out = self.o1[end]
        realized += side * q_open * (out - px)
        fees += q_open * out * cost
        return self._fin(side, i, j0, end, realized, fees, fund, eq_path, both)

    def _fin(self, side, i, j0, jx, realized, fees, fund, eq_path, both):
        net = realized - fees - fund
        return {"side": side, "sig": int(i), "j0": j0, "jx": jx, "net": net, "fees": fees, "fund": fund,
                "path": eq_path + [net], "both": both}

    def run(self, sigs, ex, a, b, cost=COST):
        ta, tb = TS(a), TS(b)
        ev = sorted([(int(i), s) for s in (1, -1) for i in np.flatnonzero(sigs[s]) if ta <= self.t4[i] + H4S < tb])
        trades, missed, busy_until = [], [], -1
        for i, s in ev:
            p = self.plan(s, i)
            if p is None:
                continue
            if p[0] < busy_until:
                missed.append((i, s))
                continue
            tr = self.trade(s, i, ex, cost)
            if tr is None:
                continue
            trades.append(tr)
            busy_until = tr["jx"]
        return trades, missed


def stats(trs):
    if not trs:
        return {"n": 0, "net": 0.0, "dd": 0.0, "no_top3": 0.0}
    eq, base = [0.0], 0.0
    for tr in trs:
        eq += [base + v for v in tr["path"]]
        base += tr["net"]
    eq = np.array(eq)
    x = np.sort([t["net"] for t in trs])
    return {"n": len(trs), "net": float(x.sum()), "dd": float(np.max(np.maximum.accumulate(eq) - eq)),
            "no_top3": float(x[:-3].sum()) if len(x) > 3 else 0.0, "win": float(np.mean(x > 0)),
            "both_in_hour": int(sum(t["both"] for t in trs))}


def main():
    pk = Path(next(a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--pk-btc=")))
    res = {}
    for mo in (False, True):
        Mk = M(pk, mo)
        sig = Mk.signals()
        tag = "минуты" if mo else "стоп первым"
        res[tag] = {}
        for w, (a, b) in WIN.items():
            res[tag][w] = {}
            for nm, ex in EXITS.items():
                trs, missed = Mk.run(sig, ex, a, b)
                st = stats(trs)
                st["missed"] = len(missed)
                st["double_cost_net"] = stats(Mk.run(sig, ex, a, b, cost=2 * COST)[0])["net"]
                res[tag][w][nm] = st
                if not mo and w.startswith("R") and ex in ("E2", "T"):
                    print(f"\n{w} {nm}: сделки")
                    for t in trs:
                        print(f"  сигнал {pd.to_datetime(Mk.t4[t['sig']] + H4S, unit='s')} {'L' if t['side'] == 1 else 'S'} "
                              f"вход {pd.to_datetime(Mk.t1[t['j0']], unit='s')} выход {pd.to_datetime(Mk.t1[min(t['jx'], len(Mk.t1) - 1)], unit='s')} "
                              f"net {t['net']:+.2f}")
                    print("  пропущено: " + ", ".join(f"{pd.to_datetime(Mk.t4[i] + H4S, unit='s')} {'L' if s == 1 else 'S'}"
                                                     for i, s in missed))
            # парно: E2 и T на входах S
            base_tr, _ = Mk.run(sig, "S", a, b)
            pair = {}
            for nm, ex in EXITS.items():
                vals = [Mk.trade(t["side"], t["sig"], ex) for t in base_tr]
                pair[nm] = float(sum(v["net"] for v in vals if v))
            res[tag][w]["парно на входах S"] = pair
        # контроль: случайный бар в том же режиме (сторона от B4, порядок B1/B4, наклон), без касания и тела
        if mo:
            continue
        ctl = {}
        for w, (a, b) in WIN.items():
            ta, tb = TS(a), TS(b)
            ctl[w] = {}
            with np.errstate(invalid="ignore"):              # тот же режим и близость к голубой, без касания и тела
                near = np.abs(Mk.c4 / Mk.B4 - 1) <= 0.015
                pool = {1: (Mk.c4 > Mk.B4) & (Mk.B1at4 > Mk.B4) & (Mk.sl4 >= 0) & near,
                        -1: (Mk.c4 < Mk.B4) & (Mk.B1at4 < Mk.B4) & (Mk.sl4 <= 0) & near}
            for ex in ("E2", "T"):
                trs, _ = Mk.run(sig, ex, a, b)
                if len(trs) < 5:
                    continue
                real = np.mean([t["net"] for t in trs])
                sides = [t["side"] for t in trs]
                pools = {s: np.flatnonzero(pool[s] & (Mk.t4 + H4S >= ta) & (Mk.t4 + H4S < tb)) for s in (1, -1)}
                if any(len(pools[s]) == 0 for s in set(sides)):
                    continue
                vals = np.empty(999)
                for q in range(999):
                    v = []
                    for s in sides:
                        for _try in range(200):
                            tr = Mk.trade(s, int(RNG.choice(pools[s])), ex)
                            if tr is not None:
                                v.append(tr["net"])
                                break
                    vals[q] = np.mean(v)
                ctl[w][ex] = {"real_mean": float(real), "ctl_median": float(np.median(vals)),
                              "rank": float((1 + (vals >= real).sum()) / 1000)}
            print(f"контроль {w}: {json.dumps(ctl[w], ensure_ascii=False)}", flush=True)
        res["контроль"] = ctl
    (HERE / "out_result.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float))
    for tag in ("стоп первым", "минуты"):
        print(f"\n== Итоги ({tag}): сделки · net USDT · просадка · без 3 лучших · ×2 расходы · пропущено · касаний обоих в часе")
        for w in WIN:
            print(f"-- {w}")
            for nm in EXITS:
                r = res[tag][w][nm]
                print(f"  {nm}: {r['n']} · {r['net']:+.2f} · {r['dd']:.2f} · {r['no_top3']:+.2f} · {r['double_cost_net']:+.2f} · "
                      f"{r['missed']} · {r.get('both_in_hour', 0)}")
            print("  парно на входах S: " + json.dumps({k: round(v, 2) for k, v in res[tag][w]['парно на входах S'].items()},
                                                       ensure_ascii=False))


if __name__ == "__main__":
    main()
