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
    assert "Топ-трейдеры Binance: доля лонгов в их позициях 59% (L/S 1.46)" in text
    assert "за сутки доля лонгов −6 п.п.; вчера +1 п.п. → доля лонгов снизилась" in text
    assert "OI): −4.2% (вчера +1.7%) → позиции сокращали на падении" in text
    assert "вчера $6.5M / $41.7M" in text
    concl = next(x for x in out if x.startswith("✅ Вывод:"))
    assert "вчера рост шёл с ростом позиций, сегодня падение с их сокращением" in concl
    assert "доля лонгов у топов снизилась" in concl and "фандинг остыл" in concl
    assert "направления нет" in concl                                        # 47/53 — шум, не «перевес»
    # 27.10 (оператор: «не каждый день в пределах нормы»): шумовая статистика и раздел «раньше» не печатаются
    assert "в пределах шума" not in text and "📌 Раньше" not in text and "57% против 50%" not in concl


def test_history_section_only_on_real_difference():
    q = {**QSTAT, "up": 0.66, "up_diff": True}
    out = story.compose("BTCUSDT", LV, None, q, COND,
                        {"n": 600, "p_up": 0.39, "lo": 0.35, "hi": 0.43, "halves": [0.40, 0.38]}, ST, cond_y=COND_Y)
    text = "\n".join(out)
    assert "📌 Раньше в таком состоянии (2 года BTC):" in text
    assert "рост на следующий день 66%" in text and "заметно чаще" in text
    assert "сначала −1%, чем +1%, в 61% случаев" in text
    concl = next(x for x in out if x.startswith("✅ Вывод:"))
    assert "66% против 50% обычно — заметное отличие" in concl


def test_route_phrase_thresholds():
    weak = {"n": 123, "p_up": 0.39, "lo": 0.31, "hi": 0.48, "halves": [0.41, 0.35]}
    line, verdict = story.route_phrase(weak)
    # 25.10 (аудит GPT): 39% при n 123 — ниже 50% на 95%, но не с поправкой на 10 состояний → «слабый»
    assert verdict.startswith("слабый перевес вниз") and "61%" in verdict
    strong = {"n": 600, "p_up": 0.39, "lo": 0.35, "hi": 0.43, "halves": [0.40, 0.38]}
    assert story.route_phrase(strong)[1].startswith("устойчивый перевес вниз")
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


def test_oi_labels_not_causal_in_brief_and_fallback():
    """25.10 (перепроверка GPT): нижний блок писал «закрывают лонги» из OI↓ и цены↓; запасной вывод — «без смены плеча»
    при неизменном общем OI. Ни то ни другое из OI не следует."""
    from pathlib import Path
    from services.market_brief import brief
    src = Path(brief.__file__).read_text(encoding="utf-8")
    for b in ("закрывают лонги", "закрывают шорты", "новые позиции в рост", "новые позиции в падение"):
        assert f'"{b}"' not in src, b
    s = story.conclusion("", "", {}, {"ret": 0.0}, {}, {}, None, "направления нет (≈50/50)")
    assert "без смены плеча" not in s and "могли уравновеситься" in s


def _story_env(tmp_path, monkeypatch, block):
    monkeypatch.setattr(regime_watch, "DELIVERY_LOG", tmp_path / "d.jsonl")
    monkeypatch.setattr(regime_watch, "CARD_STATE", tmp_path / "card.json")
    monkeypatch.setattr(regime_watch, "STORY_STATE", tmp_path / "story.json")
    monkeypatch.setattr(regime_watch, "STORY_LOG", tmp_path / "story_log.jsonl")
    monkeypatch.setattr(regime_watch, "_card_push_enabled", lambda: True)
    monkeypatch.setattr(regime_watch, "_tv_line_enabled", lambda: False)
    monkeypatch.setattr(regime_watch, "build_card", lambda now: "карточка")
    monkeypatch.setattr(story, "block", block)


def test_g6_story_retried_after_card_already_sent(tmp_path, monkeypatch):
    """25.10 (аудит GPT 481385e G6): рассказ упал, карточка ушла → до фикса дата карточки закрывала день и рассказ не
    повторялся никогда. Теперь следующий проход досылает рассказ, карточку не дублирует."""
    calls = []

    def block(now=None):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("Binance не ответил")
        return ["🧭 BTC аналитика"]
    _story_env(tmp_path, monkeypatch, block)
    now = datetime(2026, 10, 23, 6, 1, tzinfo=timezone.utc)
    sent = []
    assert regime_watch.maybe_send_regime_card(send_fn=sent.append, now=now) is True
    assert sent == ["карточка"]
    assert regime_watch.maybe_send_regime_card(send_fn=sent.append, now=now) is False
    assert sent == ["карточка", "🧭 BTC аналитика"]
    assert regime_watch.maybe_send_regime_card(send_fn=sent.append, now=now) is False
    assert sent == ["карточка", "🧭 BTC аналитика"]                       # раз в день


def test_g6_long_story_split_not_truncated_and_logged(tmp_path, monkeypatch):
    """До фикса text[:4096] срезал хвост — вывод в конце рассказа терялся. Теперь части по строкам; в журнале — полный
    текст и SHA."""
    import hashlib
    import json
    lines = [f"строка {i} " + "х" * 90 for i in range(60)] + ["ВЫВОД: итог дня"]
    _story_env(tmp_path, monkeypatch, lambda now=None: lines)
    sent = []
    regime_watch._send_story(sent.append, datetime(2026, 10, 23, 6, 1, tzinfo=timezone.utc), "2026-10-23")
    full = "\n".join(lines)
    assert len(sent) >= 2 and all(len(p) <= 4096 for p in sent) and "\n".join(sent) == full
    assert sent[-1].endswith("ВЫВОД: итог дня")
    rec = json.loads((tmp_path / "story_log.jsonl").read_text(encoding="utf-8"))
    assert rec["text"] == full and rec["sha256"] == hashlib.sha256(full.encode("utf-8")).hexdigest()
    assert rec["parts"] == len(sent)


def test_top_line_compares_with_two_year_norm():
    """24.10: «куда стоят топы» — доля в % и сравнение с квартилями L/S за 2 года."""
    hist = sorted([1.0 + i * 0.01 for i in range(200)])                       # 1.00…2.99, квартили ≈1.50 / 2.49
    t, y = {"top_ls": 1.30, "dls": 0.0}, {"dls": 0.0}
    line = story.top_line(t, y, {}, hist)[0]
    assert "доля лонгов в их позициях 57%" in line and "обычно 1.99, сейчас выше, чем в 15% дней за 2 года — лонгов меньше обычного" in line
    assert "в норме" in story.top_line({"top_ls": 2.0, "dls": 0.0}, y, {}, hist)[0]
    assert "лонгов больше обычного" in story.top_line({"top_ls": 2.8, "dls": 0.0}, y, {}, hist)[0]


def test_yday_hl_line_format(monkeypatch):
    """24.10: вчерашние H/L с замеренной пометкой «чаще пробой» (сеть подменена)."""
    import io
    import json as _json
    rows = [[0, "1", "84900.5", "81100.2", "1", "1"], [1, "1", "1", "1", "1", "1"]]
    monkeypatch.setattr(story.urllib.request, "urlopen", lambda url, timeout=20: io.BytesIO(_json.dumps(rows).encode()))
    line = story.yday_hl_line("BTCUSDT")
    assert line.startswith("🧱 Вчера H 84,900 / L 81,100") and "диагностика" in line and "не сетап" in line


def test_no_unproven_causal_phrases():
    """25.10 (аудит GPT A1): по OI и цене не выводятся «новые лонги/шорты», «эти же лонги», «новых продавцов нет»;
    по L/S топов — «добавили/сократили лонги»; по фандингу — «перегрев». Все шаблоны вывода проверяются целиком."""
    banned = ("новых лонгах", "новых шортах", "эти же", "новых продавцов", "добавили лонгов", "сократили лонги",
              "перегрет", "вымывание плеча", "шорт-сквиз")
    texts = list(story.DRIVER.values()) + list(story.SHORT_OI.values()) + list(story.LINK.values())
    for (op_y, op) in list(story.LINK) + [(o, o) for o in story.DRIVER]:
        for top in ("топ-трейдеры добавили лонгов", "топ-трейдеры сократили лонги", ""):
            texts.append(story.conclusion(op, op_y, {"top_ls": top, "funding": "фандинг высокий"},
                                          {"ret": -0.01, "funding": 0.0003}, {"funding": 0.0001},
                                          {"long_usd": 3e6, "short_usd": 1e6}, None, "направления нет (≈50/50)"))
    for t in texts:
        assert not any(b in t for b in banned), t
