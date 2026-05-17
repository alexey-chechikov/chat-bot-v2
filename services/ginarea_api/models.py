from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from typing import Any, cast

from dateutil.parser import isoparse  # type: ignore[import-untyped]


def _parse_datetime(value: str | None) -> datetime | None:
    if value in (None, ""):
        return None
    return cast(datetime, isoparse(value))


def _dump_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat().replace("+00:00", "Z")


class BotStatus(IntEnum):
    CREATED = 0
    STARTING = 1
    ACTIVE = 2
    PAUSED = 3
    DISABLE_IN = 4
    FAILED = 10
    STOPPING = 11
    STOPPED = 12
    CLOSING = 13
    FINISHED = 14
    TP_STOPPED = 15
    SL_STOPPED = 16


class Side(IntEnum):
    LONG = 1
    SHORT = 2


@dataclass(frozen=True, slots=True)
class GapParams:
    isg: float | None = None
    tog: float | None = None
    minS: float | None = None
    maxS: float | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> GapParams:
        return cls(
            isg=d.get("isg"),
            tog=d.get("tog"),
            minS=d.get("minS"),
            maxS=d.get("maxS"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"isg": self.isg, "tog": self.tog, "minS": self.minS, "maxS": self.maxS}


@dataclass(frozen=True, slots=True)
class QuantityParams:
    minQ: float | None = None
    maxQ: float | None = None
    qr: float | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> QuantityParams:
        return cls(minQ=d.get("minQ"), maxQ=d.get("maxQ"), qr=d.get("qr"))

    def to_dict(self) -> dict[str, Any]:
        return {"minQ": self.minQ, "maxQ": self.maxQ, "qr": self.qr}


@dataclass(frozen=True, slots=True)
class BorderParams:
    bottom: float | None = None
    top: float | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> BorderParams:
        return cls(bottom=d.get("bottom"), top=d.get("top"))

    def to_dict(self) -> dict[str, Any]:
        return {"bottom": self.bottom, "top": self.top}


@dataclass(frozen=True, slots=True)
class TrailingParams:
    mdTr: float | None = None
    minToTr: int | None = None
    tr: float | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TrailingParams:
        return cls(mdTr=d.get("mdTr"), minToTr=d.get("minToTr"), tr=d.get("tr"))

    def to_dict(self) -> dict[str, Any]:
        return {"mdTr": self.mdTr, "minToTr": self.minToTr, "tr": self.tr}


@dataclass(frozen=True, slots=True)
class StopLossProfileParams:
    m: int | None = None
    tp: float | None = None
    pp: int | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> StopLossProfileParams:
        return cls(m=d.get("m"), tp=d.get("tp"), pp=d.get("pp"))

    def to_dict(self) -> dict[str, Any]:
        return {"m": self.m, "tp": self.tp, "pp": self.pp}


@dataclass(frozen=True, slots=True)
class DefaultGridParams:
    gs: float | None = None
    gsr: float | None = None
    maxOp: int | None = None
    side: Side | None = None
    p: bool | None = None
    cf: float | None = None
    hedge: bool | None = None
    leverage: int | None = None
    ul: object | None = None
    dsblin: bool | None = None
    dsblinbtr: bool | None = None
    dsblinbap: bool | None = None
    obap: bool | None = None
    ris: bool | None = None
    slt: bool | None = None
    tsl: float | None = None
    lsl: float | None = None
    ttp: float | None = None
    ttpinc: float | None = None
    border: BorderParams = field(default_factory=BorderParams)
    gap: GapParams = field(default_factory=GapParams)
    q: QuantityParams = field(default_factory=QuantityParams)
    tr: TrailingParams = field(default_factory=TrailingParams)
    slp: StopLossProfileParams = field(default_factory=StopLossProfileParams)
    # 2026-05-17: passthrough for fields not explicitly modeled (e.g. `in`
    # start/stop conditions). Previously these were silently dropped by
    # from_dict → set_params caused GinArea API to reject with
    # `conditions array is empty in start block` errorCode:-1.
    # Fix: preserve raw dict, re-emit unknown keys on to_dict.
    extra_raw: dict = field(default_factory=dict)

    _EXPLICIT_KEYS = frozenset({
        "gs", "gsr", "maxOp", "side", "p", "cf", "hedge", "leverage", "ul",
        "dsblin", "dsblinbtr", "dsblinbap", "obap", "ris", "slt", "tsl",
        "lsl", "ttp", "ttpinc", "border", "gap", "q", "tr", "slp",
    })

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> DefaultGridParams:
        side = d.get("side")
        # Capture any keys we don't explicitly model — pass them through verbatim
        extras = {k: v for k, v in d.items() if k not in cls._EXPLICIT_KEYS}
        return cls(
            gs=d.get("gs"),
            gsr=d.get("gsr"),
            maxOp=d.get("maxOp"),
            side=Side(side) if side is not None else None,
            p=d.get("p"),
            cf=d.get("cf"),
            hedge=d.get("hedge"),
            leverage=d.get("leverage"),
            ul=d.get("ul"),
            dsblin=d.get("dsblin"),
            dsblinbtr=d.get("dsblinbtr"),
            dsblinbap=d.get("dsblinbap"),
            obap=d.get("obap"),
            ris=d.get("ris"),
            slt=d.get("slt"),
            tsl=d.get("tsl"),
            lsl=d.get("lsl"),
            ttp=d.get("ttp"),
            ttpinc=d.get("ttpinc"),
            border=BorderParams.from_dict(dict(d.get("border") or {})),
            gap=GapParams.from_dict(dict(d.get("gap") or {})),
            q=QuantityParams.from_dict(dict(d.get("q") or {})),
            tr=TrailingParams.from_dict(dict(d.get("tr") or {})),
            slp=StopLossProfileParams.from_dict(dict(d.get("slp") or {})),
            extra_raw=extras,
        )

    def to_dict(self) -> dict[str, Any]:
        # Start from extras (passthrough fields like `in`, `stop`), then overlay
        # explicit modeled fields — explicit values win on conflict.
        out: dict[str, Any] = dict(self.extra_raw or {})
        out.update({
            "gs": self.gs,
            "gsr": self.gsr,
            "maxOp": self.maxOp,
            "side": int(self.side) if self.side is not None else None,
            "p": self.p,
            "cf": self.cf,
            "hedge": self.hedge,
            "leverage": self.leverage,
            "ul": self.ul,
            "dsblin": self.dsblin,
            "dsblinbtr": self.dsblinbtr,
            "dsblinbap": self.dsblinbap,
            "obap": self.obap,
            "ris": self.ris,
            "slt": self.slt,
            "tsl": self.tsl,
            "lsl": self.lsl,
            "ttp": self.ttp,
            "ttpinc": self.ttpinc,
            "border": self.border.to_dict(),
            "gap": self.gap.to_dict(),
            "q": self.q.to_dict(),
            "tr": self.tr.to_dict(),
            "slp": self.slp.to_dict(),
        })
        return out


@dataclass(frozen=True, slots=True)
class BotStatExtension:
    sellFTP: float | None = None
    sellLTP: float | None = None
    posL: float | None = None
    posS: float | None = None
    avgPL: float | None = None
    avgPS: float | None = None
    bCnt: int | None = None
    sCnt: int | None = None
    tapb: float | None = None
    taps: float | None = None
    from_: float | None = None
    to_: float | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> BotStatExtension:
        return cls(
            sellFTP=d.get("sellFTP"),
            sellLTP=d.get("sellLTP"),
            posL=d.get("posL"),
            posS=d.get("posS"),
            avgPL=d.get("avgPL"),
            avgPS=d.get("avgPS"),
            bCnt=d.get("bCnt"),
            sCnt=d.get("sCnt"),
            tapb=d.get("tapb"),
            taps=d.get("taps"),
            from_=d.get("from"),
            to_=d.get("to"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "sellFTP": self.sellFTP,
            "sellLTP": self.sellLTP,
            "posL": self.posL,
            "posS": self.posS,
            "avgPL": self.avgPL,
            "avgPS": self.avgPS,
            "bCnt": self.bCnt,
            "sCnt": self.sCnt,
            "tapb": self.tapb,
            "taps": self.taps,
            "from": self.from_,
            "to": self.to_,
        }


@dataclass(frozen=True, slots=True)
class BotStat:
    botId: int
    accountId: int
    updatedAt: datetime
    position: float
    profit: float
    profitToTrailing: float
    currentProfit: float
    inStopCount: int
    inStopQuantity: float
    inStopInitPrice: float | None
    inStopLastPrice: float | None
    inStopPrice: float | None
    inFilledCount: int
    inFilledQuantity: float
    averagePrice: float
    triggerCount: int
    triggerQuantity: float
    firstTriggerPrice: float | None
    lastTriggerPrice: float | None
    outStopCount: int
    outStopQuantity: float
    outStopPrice: float | None
    outFilledCount: int
    outFilledQuantity: float
    tradeVolume: float
    balance: float
    liquidationPrice: float | None
    extension: BotStatExtension = field(default_factory=BotStatExtension)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> BotStat:
        return cls(
            botId=int(d["botId"]),
            accountId=int(d["accountId"]),
            updatedAt=_parse_datetime(d["updatedAt"]) or datetime.min,
            position=float(d.get("position", 0.0) or 0.0),
            profit=float(d.get("profit", 0.0) or 0.0),
            profitToTrailing=float(d.get("profitToTrailing", 0.0) or 0.0),
            currentProfit=float(d.get("currentProfit", 0.0) or 0.0),
            inStopCount=int(d.get("inStopCount", 0) or 0),
            inStopQuantity=float(d.get("inStopQuantity", 0.0) or 0.0),
            inStopInitPrice=d.get("inStopInitPrice"),
            inStopLastPrice=d.get("inStopLastPrice"),
            inStopPrice=d.get("inStopPrice"),
            inFilledCount=int(d.get("inFilledCount", 0) or 0),
            inFilledQuantity=float(d.get("inFilledQuantity", 0.0) or 0.0),
            averagePrice=float(d.get("averagePrice", 0.0) or 0.0),
            triggerCount=int(d.get("triggerCount", 0) or 0),
            triggerQuantity=float(d.get("triggerQuantity", 0.0) or 0.0),
            firstTriggerPrice=d.get("firstTriggerPrice"),
            lastTriggerPrice=d.get("lastTriggerPrice"),
            outStopCount=int(d.get("outStopCount", 0) or 0),
            outStopQuantity=float(d.get("outStopQuantity", 0.0) or 0.0),
            outStopPrice=d.get("outStopPrice"),
            outFilledCount=int(d.get("outFilledCount", 0) or 0),
            outFilledQuantity=float(d.get("outFilledQuantity", 0.0) or 0.0),
            tradeVolume=float(d.get("tradeVolume", 0.0) or 0.0),
            balance=float(d.get("balance", 0.0) or 0.0),
            liquidationPrice=d.get("liquidationPrice"),
            extension=BotStatExtension.from_dict(dict(d.get("extension") or {})),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "botId": self.botId,
            "accountId": self.accountId,
            "updatedAt": _dump_datetime(self.updatedAt),
            "position": self.position,
            "profit": self.profit,
            "profitToTrailing": self.profitToTrailing,
            "currentProfit": self.currentProfit,
            "inStopCount": self.inStopCount,
            "inStopQuantity": self.inStopQuantity,
            "inStopInitPrice": self.inStopInitPrice,
            "inStopLastPrice": self.inStopLastPrice,
            "inStopPrice": self.inStopPrice,
            "inFilledCount": self.inFilledCount,
            "inFilledQuantity": self.inFilledQuantity,
            "averagePrice": self.averagePrice,
            "triggerCount": self.triggerCount,
            "triggerQuantity": self.triggerQuantity,
            "firstTriggerPrice": self.firstTriggerPrice,
            "lastTriggerPrice": self.lastTriggerPrice,
            "outStopCount": self.outStopCount,
            "outStopQuantity": self.outStopQuantity,
            "outStopPrice": self.outStopPrice,
            "outFilledCount": self.outFilledCount,
            "outFilledQuantity": self.outFilledQuantity,
            "tradeVolume": self.tradeVolume,
            "balance": self.balance,
            "liquidationPrice": self.liquidationPrice,
            "extension": self.extension.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class Bot:
    id: int
    accountId: int
    exchangeId: int
    exchangeMarketIds: str
    strategyId: int
    name: str
    desc: str | None
    status: BotStatus
    params: DefaultGridParams
    stat: BotStat | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Bot:
        return cls(
            id=int(d["id"]),
            accountId=int(d["accountId"]),
            exchangeId=int(d["exchangeId"]),
            exchangeMarketIds=str(d["exchangeMarketIds"]),
            strategyId=int(d["strategyId"]),
            name=str(d["name"]),
            desc=d.get("desc"),
            status=BotStatus(int(d["status"])),
            params=DefaultGridParams.from_dict(dict(d.get("params") or {})),
            stat=BotStat.from_dict(dict(d["stat"])) if d.get("stat") is not None else None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "accountId": self.accountId,
            "exchangeId": self.exchangeId,
            "exchangeMarketIds": self.exchangeMarketIds,
            "strategyId": self.strategyId,
            "name": self.name,
            "desc": self.desc,
            "status": int(self.status),
            "params": self.params.to_dict(),
            "stat": self.stat.to_dict() if self.stat is not None else None,
        }


@dataclass(frozen=True, slots=True)
class Test:
    id: int
    botId: int
    accountId: int
    strategyId: int
    exchangeId: int
    exchangeMarketIds: str
    status: BotStatus
    params: DefaultGridParams
    dateFrom: datetime
    dateTo: datetime
    errorCode: int | None
    createdAt: datetime
    updatedAt: datetime
    startedAt: datetime | None
    stoppedAt: datetime | None
    stat: BotStat | None
    statHistory: list[BotStat]

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Test:
        return cls(
            id=int(d["id"]),
            botId=int(d["botId"]),
            accountId=int(d["accountId"]),
            strategyId=int(d["strategyId"]),
            exchangeId=int(d["exchangeId"]),
            exchangeMarketIds=str(d["exchangeMarketIds"]),
            status=BotStatus(int(d["status"])),
            params=DefaultGridParams.from_dict(dict(d.get("params") or {})),
            dateFrom=_parse_datetime(d["dateFrom"]) or datetime.min,
            dateTo=_parse_datetime(d["dateTo"]) or datetime.min,
            errorCode=d.get("errorCode"),
            createdAt=_parse_datetime(d["createdAt"]) or datetime.min,
            updatedAt=_parse_datetime(d["updatedAt"]) or datetime.min,
            startedAt=_parse_datetime(d.get("startedAt")),
            stoppedAt=_parse_datetime(d.get("stoppedAt")),
            stat=BotStat.from_dict(dict(d["stat"])) if d.get("stat") is not None else None,
            statHistory=[BotStat.from_dict(dict(item)) for item in list(d.get("statHistory") or [])],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "botId": self.botId,
            "accountId": self.accountId,
            "strategyId": self.strategyId,
            "exchangeId": self.exchangeId,
            "exchangeMarketIds": self.exchangeMarketIds,
            "status": int(self.status),
            "params": self.params.to_dict(),
            "dateFrom": _dump_datetime(self.dateFrom),
            "dateTo": _dump_datetime(self.dateTo),
            "errorCode": self.errorCode,
            "createdAt": _dump_datetime(self.createdAt),
            "updatedAt": _dump_datetime(self.updatedAt),
            "startedAt": _dump_datetime(self.startedAt),
            "stoppedAt": _dump_datetime(self.stoppedAt),
            "stat": self.stat.to_dict() if self.stat is not None else None,
            "statHistory": [item.to_dict() for item in self.statHistory],
        }
