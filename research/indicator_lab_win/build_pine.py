"""Собирает bot7_operator_strategy_plus.pine из docs/tv_pine_scripts/bot7_operator_strategy_A.pine точными заменами. Каждая замена проверяется: образец должен встречаться ровно один раз. Запуск: python -X utf8 build_pine.py"""
from pathlib import Path

HERE = Path(__file__).parent
SRC = HERE.parents[1] / "docs" / "tv_pine_scripts" / "bot7_operator_strategy_A.pine"
s = SRC.read_text(encoding="utf8")


def rep(a, b):
    global s
    assert s.count(a) == 1, (s.count(a), a[:80])
    s = s.replace(a, b)


rep('// Вариант A как words2.py: шорт 2/6 ATR и X01 — галками.\n',
    '// Вариант A как words2.py: шорт 2/6 ATR и X01 — галками.\n'
    '// Простое+ (кандидат, 07.11.2026, research/indicator_lab_win/candidate.py): те же входы и выходы, но шорт запрещён при ранге ATR100% за год выше порога, размер сделки обратно пропорционален ATR100%. На резерве ещё не проверен.\n'
    '// Оповещения: при создании выбрать условие «Any alert() function call» либо одно из условий «bot7: ...», частота «Once Per Bar Close».\n')
rep('options=["Простое правило", "Вариант A"], group=grpM, tooltip="Простое правило считается на графиках 1ч и 4ч, сделки одни и те же. Вариант A — только на 1ч.")',
    'options=["Простое правило", "Простое+ (кандидат)", "Вариант A"], group=grpM, tooltip="Простое правило считается на графиках 1ч и 4ч, сделки одни и те же. Простое+ — то же плюс фильтр шорта и размер от волатильности, на резерве ещё не проверено. Вариант A — только на 1ч.")')
rep('grpO = "Вариант A (только 1ч)"\n',
    'grpP = "Простое+"\n'
    'shortRankMax = input.float(60.0, "Шорт только при ранге ATR100% не выше, %", minval=0, maxval=100, step=5, group=grpP, tooltip="Ранг за год на барах 4ч. Соседи 40–80% дают тот же знак на BTC, ETH, XRP и Bitstamp.")\n'
    '\n'
    'grpO = "Вариант A (только 1ч)"\n')
rep('H4_MS = 14400000\n', 'H4_MS = 14400000\nVOL_BARS = 2190\nSIZE_LO = 0.5\nSIZE_HI = 2.0\nSIZE_NORM = 1.18\n')
rep('runS = stratMode == "Простое правило" and (isH1 or isH4)\n',
    'isPlus = stratMode == "Простое+ (кандидат)"\nrunS = (stratMode == "Простое правило" or isPlus) and (isH1 or isH4)\n')
rep('f_4h() =>\n    [close, f_tema(close, 50), f_tema(close, 100), f_tema(close, 200), ta.ema(close, 200), ta.atr(14)]\n',
    'f_4h() =>\n    p = ta.atr(100) / close\n    m = ta.median(p, VOL_BARS)\n    [close, f_tema(close, 50), f_tema(close, 100), f_tema(close, 200), ta.ema(close, 200), ta.atr(14), ta.percentrank(p, VOL_BARS), m[1], p]\n')
rep('    a = ta.atr(14)\n    [close[1], g[1], y[1], r[1], b[1], a[1]]\n',
    '    a = ta.atr(14)\n    p = ta.atr(100) / close\n    rk = ta.percentrank(p, VOL_BARS)\n    m = ta.median(p, VOL_BARS)\n    [close[1], g[1], y[1], r[1], b[1], a[1], rk[1], m[2], p[1]]\n')
rep('[c4a, g4a, y4a, r4a, b4a, t4a] = request.security', '[c4a, g4a, y4a, r4a, b4a, t4a, rka, mda, pca] = request.security')
rep('[c4b, g4b, y4b, r4b, b4b, t4b] = request.security', '[c4b, g4b, y4b, r4b, b4b, t4b, rkb, mdb, pcb] = request.security')
rep('atr4 = new4 ? t4a : t4b\n',
    'atr4 = new4 ? t4a : t4b\n'
    'rk4  = new4 ? rka : rkb\n'
    'md4  = new4 ? mda : mdb\n'
    'pc4  = new4 ? pca : pcb\n'
    'sizeNow = (na(md4) or na(pc4) or pc4 <= 0 ? 1.0 : math.max(math.min(md4 / pc4, SIZE_HI), SIZE_LO)) / SIZE_NORM\n'
    'shortOk = na(rk4) or rk4 <= shortRankMax\n')
rep('var float entryAtr = na\n', 'var float entryAtr = na\nvar float entrySize = 1.0\n')
rep('int entryFlag = 0\nbool closeNow = false\n', 'int entryFlag = 0\nint exitFlag = 0\nbool closeNow = false\n')
rep('w = runA and optHalf and side == 1 and not entryDesc ? 0.5 : 1.0\n', 'w = runA and optHalf and side == 1 and not entryDesc ? 0.5 : runS and isPlus ? entrySize : 1.0\n')
rep('        side := 0\n        tag := ""\n\n    // новый вход простого правила\n',
    '        exitFlag := side\n'
    '        alert(syminfo.ticker + " bot7: закрыть " + (side == 1 ? "лонг" : "шорт") + " по " + str.tostring(xPx, format.mintick) + ", " + xWhy + ", сделка " + str.tostring(net, "+0.00;-0.00") + "%", alert.freq_once_per_bar_close)\n'
    '        side := 0\n        tag := ""\n\n    // новый вход простого правила\n')
rep('        else if rG <= -K4\n            oSide := -1\n            oTag := "под синей"\n',
    '        else if rG <= -K4 and (not isPlus or shortOk)\n            oSide := -1\n            oTag := "под синей"\n')
rep('        entryDesc := oSide == 1 ? (overBL and rising) : inDesc\n        entryFlag := 1\n',
    '        entryDesc := oSide == 1 ? (overBL and rising) : inDesc\n'
    '        entrySize := runS and isPlus ? sizeNow : 1.0\n'
    '        entryFlag := 1\n'
    '        alert(syminfo.ticker + " bot7: " + (oSide == 1 ? "ЛОНГ" : "ШОРТ") + " по " + str.tostring(close, format.mintick) + (runS and isPlus ? ", размер ×" + str.tostring(entrySize, "0.00") : "") + (runS ? ", выход: 2 закрытия 4ч " + (oSide == 1 ? exitLine : "над зелёной") : ""), alert.freq_once_per_bar_close)\n')
rep('txt = (oSide == 1 ? "L " : "S ") + oTag + (half ? " ½" : "")\n', 'txt = (oSide == 1 ? "L " : "S ") + oTag + (half ? " ½" : "") + (runS and isPlus ? " ×" + str.tostring(entrySize, "0.00") : "")\n')
rep('// ── фаза и серые окна: как research/chart_walk_20261105/state_map.py\n',
    '// ── оповещения: те же события, что и alert() выше, для обычного окна создания оповещения\n'
    'alertcondition(entryFlag == 1 and side == 1, title="bot7: вход в лонг", message="{{ticker}} bot7: вход в лонг, цена {{close}}")\n'
    'alertcondition(entryFlag == 1 and side == -1, title="bot7: вход в шорт", message="{{ticker}} bot7: вход в шорт, цена {{close}}")\n'
    'alertcondition(exitFlag == 1, title="bot7: закрыть лонг", message="{{ticker}} bot7: закрыть лонг, цена {{close}}")\n'
    'alertcondition(exitFlag == -1, title="bot7: закрыть шорт", message="{{ticker}} bot7: закрыть шорт, цена {{close}}")\n'
    '\n'
    '// ── фаза и серые окна: как research/chart_walk_20261105/state_map.py\n')
rep('", шорт " + str.tostring(sShort, "+0.0;-0.0") + ")"\n',
    '", шорт " + str.tostring(sShort, "+0.0;-0.0") + ")"\n'
    '        volTxt = "Волатильность: ранг " + (na(rk4) ? "нет данных" : str.tostring(rk4, "#") + "%") + ", шорт " + (shortOk ? "разрешён" : "запрещён") + ", размер новой сделки ×" + str.tostring(sizeNow, "0.00") + (side != 0 ? ", открытой ×" + str.tostring(entrySize, "0.00") : "")\n')
rep('            f_span(tb, 3, sumTxt)\n        else\n', '            f_span(tb, 3, sumTxt)\n            if isPlus\n                f_span(tb, 4, volTxt)\n        else\n')
rep('            f_span(tb, 14, "Последняя: " + lastTrade)\n', '            f_span(tb, 14, "Последняя: " + lastTrade)\n            if isPlus\n                f_span(tb, 15, volTxt)\n')
(HERE / "bot7_operator_strategy_plus.pine").write_text(s, encoding="utf8")
print("строк", s.count("\n"), "байт", len(s.encode("utf8")))
