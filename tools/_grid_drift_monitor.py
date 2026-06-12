"""Live drift-monitor for alt Dynamic-Auto grid bots (consumes the tracker snapshot stream).
Идея оператора 2026-06-11: бот сам ведёт анализ ПОСЛЕ входа; при раскореляции (инструмент выпадает
из пилы в дрейф) -> эскалация: WARN -> расширить step/target ×2 -> если упорно -> закрыть.
Respects the WALL: дрейф НЕ предсказывается заранее (чоп vs тренд-старт причинно неразличимы); монитор
РЕАГИРУЕТ на ПОДТВЕРЖДённый дрейф (мешок ускоряется + позиция пригвождена одной стороной), что дешевле/раньше,
чем жёсткий −175 SL, режущий на самом дне. Связано с project_dynamic_grid_solution (EXIT-FAST) и
project_alt_grid_live_run. Поля берём из tracker-снимков (snapshots.csv Мака)."""
import numpy as np, pandas as pd

WIN_MIN = 20          # окно для ускорения мешка / постоянства знака позиции

# --- ДЕКОРРЕЛЯЦИЯ vs BTC (ранний сигнал, ретро 10.06: WLD 15:38@мешок-48 vs bag-Stage3 16:14@-143,
#     36 мин раньше, 0 ложняков SOL/XRP; см. ANSWERS_DRIFT_3Q_WIN_2026-06-12.md). КОМПЛЕМЕНТ к assess():
#     ловит ИДИОСИНКРАЗИЮ (alt уехал, BTC стоит); bag-монитор ловит коррелированный дрейф. n=1 — порог калибровать.
IDIO_WIN_MIN = 30     # окно excess-хода, мин
IDIO_THRESH = -3.0    # excess ≤ −3% против стороны грида -> сигнал
def idio_excess(alt_close_1m, btc_close_1m, win=IDIO_WIN_MIN):
    """alt/btc: pd.Series close с DatetimeIndex (1m). Возвращает Series excess-хода %, alt минус BTC за win мин.
    Сигнал: excess <= IDIO_THRESH (символ падает сильнее BTC — против лонг-ноги симметричного грида;
    для чисто-шорт книги смотреть excess >= +|thresh|)."""
    a = alt_close_1m.resample("1min").last().ffill()
    b = btc_close_1m.resample("1min").last().ffill()
    idx = a.index.intersection(b.index)
    return (a.reindex(idx).pct_change(win) - b.reindex(idx).pct_change(win)) * 100

def idio_alert(alt_close_1m, btc_close_1m, win=IDIO_WIN_MIN, thresh=IDIO_THRESH):
    """(fired: bool, excess_now: float) по последней точке. Для alt_guard: 🟠 DECORR-пинг / поднять Stage."""
    ex = idio_excess(alt_close_1m, btc_close_1m, win)
    if not len(ex.dropna()):
        return False, 0.0
    cur = float(ex.dropna().iloc[-1])
    return cur <= thresh, round(cur, 2)

def assess(df, tsl=-175.0):
    """df: снимки ОДНОГО бота до 'сейчас', sorted by ts; cols: ts, position, profit, current_profit.
    Возвращает (stage 0..3, action, метрики)."""
    d = df.copy()
    if "bag" not in d:
        d["bag"] = d["current_profit"] - d["profit"]
    cur = d.iloc[-1]
    win = d[d["ts"] >= cur["ts"] - pd.Timedelta(minutes=WIN_MIN)]
    bag_pct = cur["bag"] / tsl if tsl else 0.0                       # доля жёсткого SL, съеденная мешком (0..1+)
    runmax = float(d["position"].abs().cummax().iloc[-1])
    pos_extreme = abs(cur["position"]) / runmax if runmax > 0 else 0.0
    sign_const = (win["position"].apply(np.sign).nunique() == 1) and abs(cur["position"]) > 0
    pos_pin = pos_extreme if sign_const else pos_extreme * 0.4       # пригвождена ли поза к одному краю
    bag_accel = float(cur["bag"] - win["bag"].iloc[0])               # <0 = мешок углубляется в окне
    deepening = bag_accel < -5.0
    if bag_pct >= 0.75 and pos_pin >= 0.80 and deepening:
        stage, action = 3, "ЗАКРЫТЬ бота — дрейф подтверждён (не ждать −175 на дне)"
    elif bag_pct >= 0.55 and pos_pin >= 0.70 and deepening:
        stage, action = 2, "РАСШИРИТЬ step/target ×2 — дать коридор + крупнее доход на отскоке"
    elif bag_pct >= 0.40 and pos_pin >= 0.70:
        stage, action = 1, "WARN — односторонний дрейф, следить"
    else:
        stage, action = 0, "healthy — пила доится"
    return stage, action, dict(bag_pct=round(bag_pct, 2), pos_pin=round(pos_pin, 2),
                               bag=round(float(cur["bag"]), 1), total=round(float(cur["current_profit"]), 1),
                               bag_accel=round(bag_accel, 1))

def replay(df, tsl=-175.0, name=""):
    """Прогон монитора по истории бота: печатает переходы стадий + точку Stage-3 (где бы закрыли)."""
    d = df.rename(columns={"ts_utc": "ts"}).copy()
    d["ts"] = pd.to_datetime(d["ts"])
    d = d.sort_values("ts").reset_index(drop=True)
    prev, exit_at = -1, None
    for i in range(2, len(d)):
        st, act, mx = assess(d.iloc[: i + 1], tsl)
        if st != prev:
            print(f"  {d.iloc[i]['ts'].strftime('%H:%M')}  Stage {st}  {act}  | "
                  f"мешок {mx['bag']:.0f} ({mx['bag_pct']:.0%} SL) поза-pin {mx['pos_pin']:.2f} total {mx['total']:.0f}")
            prev = st
            if st == 3 and exit_at is None:
                exit_at = mx
    mxstage = "≥3 ЗАКРЫТЬ" if exit_at else "≤2"
    print(f"  >>> {name}: max stage {mxstage}; "
          + (f"закрыли бы в total {exit_at['total']:.0f} (vs факт −99)" if exit_at else "НЕ закрыли — рейнджер цел"))

if __name__ == "__main__":
    import sys
    D = "docs/CONTEXT/data/alt_run_2026-06-10/"
    sn = pd.read_csv(D + "snapshots.csv")
    for bot, nm in [(5693279219, "SOL"), (4306550166, "XRP"), (5617871752, "WLD")]:
        print(f"\n=== {nm} ===")
        replay(sn[sn.bot_id == bot], tsl=-175.0, name=nm)
