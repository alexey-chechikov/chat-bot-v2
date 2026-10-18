"""Разбор страниц CoinGlass и досверка зон — на синтетическом тексте той же структуры (не копия страниц)."""
from __future__ import annotations

import pytest

from services.coinglass_web import collector as cg


LEVELS = ("Ключевые уровни ликвидации\nСторона\tЦена\tРасстояние\tКредитное плечо\tСила\t\n"
          "Шорт\t82 466,5\t+1.98%\tВысокое кредитное плечо\t87.2\t\n\n"
          "Последняя цена 80 861,5\n"
          "Лонг\t80 487,0\t-0.46%\tСреднее плечо\t64.4\t\n"
          "▼ Медвежий разворот 10-18 13:26\n"
          "Магнитные зоны\nШорты ликвидируются\n1\n82 277,0 – 83 287,8\n+2.37%\n1 199\nширина 1.25%\n"
          "2\n83 287,8 – 83 835,4\n+3.31%\n424\nширина 0.68%\n3\n—\nНа этой стороне нет значимых зон\n"
          "Лонги ликвидируются\n1\n79 792,1 – 80 592,3\n-0.82%\n920\nширина 0.99%\n"
          "Баланс ближнего поля\nСила позиций\nЛонги 50% · 1 361\nШорт 50% · 1 366\n"
          "Сбалансировано · доля шортов -8 п.п. vs 24 ч назад\n")

LIQ = ("Биткоин Ликвидации\n$69,831,959\nЛонг : $47,219,859\nШорт : $22,612,099\n"
       "Крупнейшая одиночная ликвидация\n$11,668,150\nЛиквидации vs ср. 7 дн.\n0.73x Нормально\n"
       "1h Rekt\n$12.04M\nЛонг\n$10.51M\nШорт\n$1.53M\n"
       "Рейтинг\nBinance\n\t\n$30.11M\n\t\n$4.98M\n\t\n$35.09M\n\t50.25%\n")


def test_parse_levels():
    r = cg.parse_levels(LEVELS)
    assert r["price"] == 80861.5
    assert [z["lo"] for z in r["zones_short"]] == [82277.0, 83287.8] and r["zones_short"][0]["strength"] == 1199
    assert r["zones_long"][0] == {"rank": 1, "lo": 79792.1, "hi": 80592.3, "dist_pct": -0.82, "strength": 920.0,
                                  "width_pct": 0.99}
    assert r["near"] == {"long_pct": 50, "long_strength": 1361.0, "short_pct": 50, "short_strength": 1366.0,
                         "short_pp_24h": -8}
    assert {k["side"] for k in r["key_levels"]} == {"short", "long"}
    assert r["clld"][0][1] == "Медвежий"


def test_parse_levels_rejects_unloaded_page():
    with pytest.raises(ValueError):
        cg.parse_levels("Последняя цена —\nМагнитные зоны\nШорты ликвидируются\n1\n—\n")


def test_parse_liquidations():
    r = cg.parse_liquidations(LIQ)
    assert r["total_24h"] == 69831959 and r["long_24h"] == 47219859 and r["vs_7d"] == 0.73
    assert r["windows"]["1h"] == {"total": 12.04e6, "long": 10.51e6, "short": 1.53e6}
    assert r["exchanges"]["Binance"]["share_pct"] == 50.25


