/* Ядро эпизода сетки — та же механика, что research/weex/regime_grid.py run() для одной стороны (сверка:
   validate_kernel.py, расхождение 0 до округления):
   - вход — лимитка на шаг от крайнего открытого лота (лонг — нижнего, шорт — верхнего); без лотов опорная цена тянется
     за ценой (лонг — за максимумом, шорт — за минимумом); один вход за точку пути; потолок номинала и число лотов;
   - тейк каждого лота — entry·(1±цель), мейкер; фандинг на минуте расчёта по open (лонг платит положительную ставку);
   - путь минуты: 4 точки (open, low/high по цвету, close);
   - эпизод [i0, i1): входы до i_off; после i_off только тейки; закрытие остатка по рынку на open минуты i1 тейкером
     с проскальзыванием (фандинг минуты i1 платится до закрытия, как в regime_grid);
   - plus_mode=1 (схема оператора «выключать в плюсе»): после i_off остаток закрывается по рынку на close первой
     минуты, где полный капитал эпизода ≥ 0; если не дождались — на i1.
   Выход на эпизод (K=12): net, tp_gross, fees, funding, exit_pnl, bag_before_exit, dd, fills, tps, lots_at_exit,
   end_index, peak_cost, exit_fee. */
#include <math.h>

#define MAXL 1024
#define K 13

static void one(const double *pts, const double *o, const double *c, const double *fund, long n,
                long i0, long i_off, long i1, int d, int plus_mode, double lim, double g, double t, double order_usd,
                double qty_fixed, double cap, int max_lots, double mk, double tk, double sl, double *out) {
    double e[MAXL], q[MAXL], tp[MAXL];
    int nl = 0, has_ref = 0, fills = 0, tps = 0;
    double real = 0, fee = 0, fnd = 0, sq = 0, sqe = 0, ref = 0, peak = 0, dd = 0, tpg = 0, peak_cost = 0;
    double eq = 0;
    long i, end = i1;
    int done = 0;
    if (max_lots > MAXL) max_lots = MAXL;
    for (i = i0; i < i1 && i < n; i++) {
        if (fund[i] != 0.0 && nl > 0) fnd += d * fund[i] * sq * o[i];
        for (int k = 0; k < 4; k++) {
            double p = pts[i * 4 + k];
            if (nl > 0) {
                int w = 0;
                for (int j = 0; j < nl; j++) {
                    if ((d > 0 && p >= tp[j]) || (d < 0 && p <= tp[j])) {
                        double pr = d * q[j] * (tp[j] - e[j]);
                        real += pr;
                        tpg += pr;
                        fee += q[j] * tp[j] * mk;
                        sq -= q[j];
                        sqe -= q[j] * e[j];
                        tps++;
                    } else {
                        e[w] = e[j]; q[w] = q[j]; tp[w] = tp[j]; w++;
                    }
                }
                nl = w;
                if (nl == 0) { sq = 0; sqe = 0; }
            }
            if (i >= i_off) continue;
            if (nl > 0) {
                ref = e[0];
                for (int j = 1; j < nl; j++) ref = d > 0 ? fmin(ref, e[j]) : fmax(ref, e[j]);
            } else if (!has_ref) {
                ref = p; has_ref = 1;
            } else {
                ref = d > 0 ? fmax(ref, p) : fmin(ref, p);
            }
            double lvl = ref * (1 - d * g);
            if (nl < max_lots && ((d > 0 && p <= lvl && lvl <= lim) || (d < 0 && p >= lvl && lvl >= lim))) {
                double px = lvl;
                double qq = qty_fixed > 0 ? qty_fixed : order_usd / px;
                double cost = sqe, alt = sq * p;
                if (alt > cost) cost = alt;
                if (cost + qq * px <= cap) {
                    e[nl] = px; q[nl] = qq; tp[nl] = px * (1 + d * t); nl++;
                    fee += qq * px * mk;
                    sq += qq; sqe += qq * px;
                    fills++;
                    if (sqe > peak_cost) peak_cost = sqe;
                }
            }
        }
        eq = real - fee - fnd + d * (sq * c[i] - sqe);
        if (eq > peak) peak = eq;
        if (eq - peak < dd) dd = eq - peak;
        if (plus_mode && i >= i_off && eq >= 0) {      /* «в плюсе» — закрыть остаток на close этой минуты */
            double bag = d * (sq * c[i] - sqe), ex = 0;
            double px = c[i] * (1 - d * sl), xf = 0;
            for (int j = 0; j < nl; j++) { ex += d * q[j] * (px - e[j]); xf += q[j] * px * tk; }
            fee += xf;
            out[4] = ex; out[5] = bag; out[9] = nl; out[12] = xf;
            real += ex; nl = 0; sq = 0; sqe = 0; end = i + 1; done = 1;
            break;
        }
    }
    if (!done) {
        double ex = 0, bag = 0, px;
        long last = (i1 < n ? i1 : n) - 1;
        if (i1 < n) {
            if (fund[i1] != 0.0 && nl > 0) fnd += d * fund[i1] * sq * o[i1];
            px = o[i1] * (1 - d * sl);
        } else {
            px = c[n - 1] * (1 - d * sl);
        }
        double xf = 0;
        bag = d * (sq * c[last] - sqe);
        for (int j = 0; j < nl; j++) { ex += d * q[j] * (px - e[j]); xf += q[j] * px * tk; }
        fee += xf;
        out[4] = ex; out[5] = bag; out[9] = nl; out[12] = xf;
        real += ex;
        end = i1 < n ? i1 : n;
    }
    eq = real - fee - fnd;
    if (eq - peak < dd) dd = eq - peak;
    out[0] = eq; out[1] = tpg; out[2] = fee; out[3] = fnd; out[6] = dd; out[7] = fills; out[8] = tps;
    out[10] = (double)end; out[11] = peak_cost;
}

void batch(const double *pts, const double *o, const double *c, const double *fund, long n,
           const long *i0, const long *i_off, const long *i1, const int *side, const double *lim, long m, int plus_mode,
           double step, double tgt, double order_usd, double qty_fixed, double cap, int max_lots,
           double mk, double tk, double sl, double *out) {
    for (long k = 0; k < m; k++)
        one(pts, o, c, fund, n, i0[k], i_off[k], i1[k], side[k], plus_mode, lim[k], step / 100, tgt / 100, order_usd,
            qty_fixed, cap, max_lots, mk, tk, sl, out + k * K);
}
