"""Retrospective closed-price paths for four preselected loser/winner pairs."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import pickle
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parent
PAIRS=[
    ("Лонг над синей: развитие и возврат", "над синей",1,"2023-05-28 20:00","2023-04-10 20:00"),
    ("Лонг над синей: похожий поздний вход", "над синей",1,"2023-08-29 20:00","2023-10-16 08:00"),
    ("Шорт под синей: отдача и продолжение", "под синей",-1,"2024-10-10 00:00","2023-05-08 00:00"),
    ("432: срыв и развившийся пробой", "432",1,"2026-10-21 16:00","2025-05-08 04:00"),
]

def main():
    cache=pickle.load((ROOT/"replay_cache.pkl").open("rb"))
    data=cache["Binance"]
    a=data["a"]
    fig,axes=plt.subplots(2,2,figsize=(15,10.5))
    plt.rcParams.update({"font.family":"DejaVu Sans","font.size":10})
    records=[]
    for ax,(title,tag,side,bad,good) in zip(axes.flat,PAIRS):
        for when,color,kind in [(bad,"#c13b39","Убыток"),(good,"#167d56","Прибыль")]:
            t0=int(pd.Timestamp(when,tz="UTC").timestamp())
            e=data["trades"][(t0,tag,side)]
            p=e["pos"]
            i0,i1=int(p["entry_i"]),int(e["i"])
            times=np.asarray(a["t"][i0:i1+1])
            x=(times-t0)/3600
            px=np.asarray(a["c"][i0:i1+1],float)
            y=side*(px-p["entry"])/p["atr"]
            # Exact entry and baseline exit fills instead of inventing endpoint prices.
            y[0]=0.
            y[-1]=side*(e["px"]-p["entry"])/p["atr"]
            label=f"{kind}: {pd.Timestamp(when):%d.%m.%Y}; net {e['res']:+.2f}% базы"
            ax.plot(x,y,color=color,lw=1.8,label=label,zorder=3)
            ax.plot(x[-1],y[-1],"o",ms=6,mfc="white",mec=color,mew=1.8,zorder=5)
            add_h=None
            if tag in ["над синей","под синей"] and p["add_done"]:
                add_h=(p["add_t"]-t0)/3600
                add_y=side*(p["add_px"]-p["entry"])/p["atr"]
                ax.scatter([add_h],[add_y],marker="^",s=58,color=color,edgecolor="white",linewidth=.7,zorder=6)
            records.append(dict(panel=title,outcome=kind,type=tag,side=side,entry_utc=when,exit_utc=pd.Timestamp(e["t"],unit="s",tz="UTC").isoformat(),
                elapsed_hours=float(x[-1]),price_points=len(x),entry_price=p["entry"],entry_ATR=p["atr"],corrected_final_net=e["res"],add_elapsed_h=add_h,
                continuous_hourly=bool(np.all(np.diff(times)==3600))))
        ax.axhline(0,color="#3b4252",lw=.9,zorder=1)
        for h in [4,12,24]:
            ax.axvline(h,color="#75808c",ls="--",lw=.8,alpha=.55,zorder=1)
        ax.set_title(title,loc="left",fontweight="bold",pad=10)
        ax.set_xlabel("Часов после входа (фактическое время)")
        ax.set_ylabel("Ход цены в сторону позиции, ATR входа")
        ax.grid(axis="y",color="#e3e7eb",lw=.7)
        ax.set_axisbelow(True)
        ax.spines[["top","right"]].set_visible(False)
        ax.legend(loc="best",fontsize=8.2,frameon=True,framealpha=.92)
        ax.text(.01,.98,"Вертикали: 4 / 12 / 24 ч",transform=ax.transAxes,va="top",fontsize=8,color="#59636e")
    fig.suptitle("Как развиваются похожие входы: проигравшие и победители",fontsize=18,fontweight="bold",x=.06,ha="left",y=.98)
    fig.text(.06,.018,"Ретроспективный путь закрытий часа до базового выхода. ○ — выход, ▲ — фактический добор.\nЛинии показывают цену в ATR первого входа, а не equity. Net в легенде — % базы с весом/добором и комиссиями, без funding.",fontsize=10,color="#424b57",ha="left")
    fig.tight_layout(rect=[.04,.075,.99,.945],h_pad=2.1,w_pad=2.3)
    dest=ROOT/"results"
    dest.mkdir(exist_ok=True)
    fig.savefig(dest/"bad_trade_paths.png",dpi=170,facecolor="white")
    plt.close(fig)
    pd.DataFrame(records).to_csv(dest/"bad_trade_paths_parameters.csv",index=False,encoding="utf-8-sig")
    metadata=dict(source_cache_sha256=hashlib.sha256((ROOT/"replay_cache.pkl").read_bytes()).hexdigest(),
        matplotlib=matplotlib.__version__,size_inches=[15,10.5],dpi=170,x="actual elapsed hours, complete position, no 320h truncation",y="directional close-price move / entry ATR",pairs=records)
    (dest/"bad_trade_paths_parameters.json").write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding="utf-8")
    (dest/"bad_trade_paths.md").write_text("# Параметры рисунка\n\nРетроспективный полный путь закрытий часа для четырёх заранее выбранных пар. Ось X — фактические часы от входа; Y — side×(close−entry)/ATRentry. Каждая линия заканчивается базовым выходом. Треугольник — фактический fill добора по его времени/цене, круг — базовый выход. Вертикали4/12/24ч — точки возможного анализа. Ни один будущий экстремум не используется для входного score.\n\nПокрыты полные позиции; длиннейшая384ч, поэтому ограничение320ч не применено. Все8 путей непрерывны по часу. Суммарный net в легенде относится к позиции с её весом, ногами и комиссиями, без funding; это не величина по осиY. Сравнение не доказывает, что исход можно было уверенно различить на входе.\n\nИсточник: corrected replay cache SHA256 `"+metadata["source_cache_sha256"]+"`. Скрипт: `plot_bad_trade_paths.py`; численные параметры: CSV/JSON рядом.\n",encoding="utf-8")
    print(dest/"bad_trade_paths.png")
    print(pd.DataFrame(records).to_string(index=False))

if __name__=="__main__":main()
