"""22.10: блок «что изменилось за сутки и что из этого следует» (services/market_brief/story.py) — без сети."""
from __future__ import annotations

from datetime import datetime, timezone

from services import regime_watch
from services.market_brief import story

LV = {"price": 81967.0,
      "today": {"ret": -0.018, "oi_chg_pct": -4.2, "top_ls": 1.46, "dls": -0.42, "taker": 0.95, "funding": 0.00004},
      "yday": {"ret": 0.025, "oi_chg_pct": 1.7, "top_ls": 1.88, "dls": 0.10, "taker": 1.05, "funding": 0.00023},
      "liq": {"long_usd": 45.8e6, "short_usd": 33.5e6, "cluster": None}}
COND = {"oi_price": "OI↓ цена↓", "funding": "фандинг обычный", "top_ls": "топ-трейдеры сократили лонги"}
COND_Y = {"oi_price": "OI↑ цена↑"}
QSTAT = {"n": 163, "up": 0.57, "up_base": 0.50, "up_diff": False}
ST = {"state": "падение 2–3.5%", "px": 81967.0, "dd": -0.028, "ru": 0.004}


def test_conclusion_links_yesterday_and_today():
    out = story.compose("BTCUSDT", LV, (6.5e6, 41.7e6), QSTAT, COND,
                        {"n": 346, "p_up": 0.468, "lo": 0.42, "hi": 0.52, "halves": [0.48, 0.46]}, ST, cond_y=COND_Y)
    text = "\n".join(out)
    # 24.10: доля лонгов/шортов в %, изменение доли в п.п. (дефис в слове цел, минус у числа)
    assert "Топ-трейдеры: 59% в лонгах / 41% в шортах (L/S 1.46)" in text
    assert "за сутки доля лонгов −6 п.п.; вчера +1 п.п. → сократили лонги" in text
    assert "OI): −4.2% (вчера +1.7%) → закрывали лонги" in text
    assert "вчера $6.5M / $41.7M" in text
    concl = next(x for x in out if x.startswith("✅ Вывод:"))
    assert "вчерашний рост на новых лонгах откатили закрытием этих же лонгов" in concl
    assert "топы сократили лонги" in concl and "фандинг остыл" in concl
    assert "направления нет" in concl                                        # 47/53 — шум, не «перевес»
    assert "57% против 50% обычно — в пределах шума" in concl


def test_route_phrase_thresholds():
    weak = {"n": 123, "p_up": 0.39, "lo": 0.31, "hi": 0.48, "halves": [0.41, 0.35]}
    line, verdict = story.route_phrase(weak)
    assert verdict.startswith("устойчивый перевес вниз") and "61%" in verdict      # интервал целиком ниже 50%
    split = {"n": 369, "p_up": 0.50, "lo": 0.45, "hi": 0.55, "halves": [0.55, 0.44]}
    assert story.route_phrase(split)[1] == "направления нет (≈50/50)"            # половины расходятся
    soft = {"n": 307, "p_up": 0.56, "lo": 0.49, "hi": 0.60, "halves": [0.54, 0.57]}
    assert story.route_phrase(soft)[1].startswith("слабый перевес вверх")         # интервал задевает 50%
    assert story.route_phrase(None)[1] == "по этому состоянию данных нет"


def test_state_of_buckets():
    assert story._state_of(96.4, 100.0, 95.0) == "падение ≥3.5%"
    assert story._state_of(97.5, 100.0, 96.0) == "падение 2–3.5%"
    assert story._state_of(104.0, 104.5, 100.0) == "рост ≥3.5%"
    assert story._state_of(100.0, 100.5, 99.5) == "спокойно"


def test_story_sent_first_once_per_day(tmp_path, monkeypatch):
    monkeypatch.setattr(regime_watch, "DELIVERY_LOG", tmp_path / "d.jsonl")
    monkeypatch.setattr(regime_watch, "CARD_STATE", tmp_path / "card.json")
    monkeypatch.setattr(regime_watch, "STORY_STATE", tmp_path / "story.json")
    monkeypatch.setattr(regime_watch, "_card_push_enabled", lambda: True)
    monkeypatch.setattr(regime_watch, "_tv_line_enabled", lambda: False)
    monkeypatch.setattr(regime_watch, "build_card", lambda now: "карточка")
    monkeypatch.setattr(story, "block", lambda now=None: ["🧭 BTC аналитика"])
    now = datetime(2026, 10, 23, 6, 1, tzinfo=timezone.utc)
    sent = []

    def flaky(text):
        if text == "карточка" and not any(x == "сбой" for x in sent):
            sent.append("сбой")
            raise RuntimeError("телеграм лёг")
        sent.append(text)
    assert regime_watch.maybe_send_regime_card(send_fn=flaky, now=now) is False   # аналитика ушла, карточка — нет
    assert regime_watch.maybe_send_regime_card(send_fn=flaky, now=now) is True    # повтор: только карточка
    assert sent == ["🧭 BTC аналитика", "сбой", "карточка"]


def test_top_line_compares_with_two_year_norm():
    """24.10: «куда стоят топы» — доля в % и сравнение с квартилями L/S за 2 года."""
    hist = sorted([1.0 + i * 0.01 for i in range(200)])                       # 1.00…2.99, квартили ≈1.50 / 2.49
    t, y = {"top_ls": 1.30, "dls": 0.0}, {"dls": 0.0}
    line = story.top_line(t, y, {}, hist)[0]
    assert "57% в лонгах / 43% в шортах" in line and "обычно 1.99, сейчас выше, чем в 15% дней за 2 года — лонгов меньше обычного" in line
    assert "в норме" in story.top_line({"top_ls": 2.0, "dls": 0.0}, y, {}, hist)[0]
    assert "лонгов больше обычного" in story.top_line({"top_ls": 2.8, "dls": 0.0}, y, {}, hist)[0]


def test_yday_hl_line_format(monkeypatch):
    """24.10: вчерашние H/L с замеренной пометкой «чаще пробой» (сеть подменена)."""
    import io
    import json as _json
    rows = [[0, "1", "84900.5", "81100.2", "1", "1"], [1, "1", "1", "1", "1", "1"]]
    monkeypatch.setattr(story.urllib.request, "urlopen", lambda url, timeout=20: io.BytesIO(_json.dumps(rows).encode()))
    line = story.yday_hl_line("BTCUSDT")
    assert line.startswith("🧱 Вчера H 84,900 / L 81,100") and "57/43" in line
