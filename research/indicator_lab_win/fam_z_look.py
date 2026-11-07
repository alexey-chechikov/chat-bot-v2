"""Свод семейства З: условия раздела 6 задания против базы. Смотрит готовую таблицу."""
from pathlib import Path
import numpy as np, pandas as pd
import lab_data as ld
pd.set_option("display.width", 260, "display.max_columns", 50, "display.max_rows", 400, "display.max_colwidth", 30)
OUT = Path(__file__).parent / "out"
d = pd.read_csv(OUT / "fam_z.csv")
b = d[(d["шорт"]=="без")&(d["лонг"]=="без")&(d["пауза"]=="нет")&(d["размер"]=="постоянный")].iloc[0]
C = list(ld.COINS20)
d["монеты_итог"] = d[[f"{c}_итог" for c in C]].sum(axis=1)
d["монеты_лучше"] = sum((d[f"{c}_итог"] > b[f"{c}_итог"]).astype(int) for c in C)
d["монеты_с2025"] = d[[f"{c}_с2025" for c in C]].sum(axis=1)
d["монеты_дд"] = d[[f"{c}_просадка" for c in C]].median(axis=1)
for s in ("BTC","ETH","XRP","Bitstamp"):
    d[f"{s}_о"] = d[f"{s}_итог"]/d[f"{s}_просадка"].abs().clip(lower=1)
d["У1"] = (d["BTC_итог"]>=b["BTC_итог"])&(d["BTC_просадка"]>=b["BTC_просадка"])&(d["ETH_итог"]>=b["ETH_итог"])&(d["ETH_просадка"]>=b["ETH_просадка"])
d["У2"] = (d["BTC_с2025"]>0)&(d["ETH_с2025"]>0)
d["У3"] = (d["BTC_p1"]>0)&(d["BTC_p2"]>0)&(d["BTC_p3"]>0)
d["У4"] = d["монеты_лучше"]>=12
d["XRP_ok"] = (d["XRP_итог"]>=b["XRP_итог"])&(d["XRP_просадка"]>=b["XRP_просадка"])
d["XRP_с25"] = d["XRP_с2025"]>0
d["всё"] = d["У1"]&d["У2"]&d["У3"]&d["У4"]
b = d.loc[b.name]
print("база:", {k:b[k] for k in ("BTC_итог","BTC_просадка","BTC_с2025","ETH_итог","ETH_просадка","ETH_с2025","XRP_итог","XRP_просадка","XRP_с2025","Bitstamp_итог","Bitstamp_просадка")}, "монеты", b["монеты_итог"], "дд", b["монеты_дд"], "с2025", b["монеты_с2025"])
print("вариантов", len(d), "У1", int(d["У1"].sum()), "У1+У2", int((d["У1"]&d["У2"]).sum()), "+У3", int((d["У1"]&d["У2"]&d["У3"]).sum()), "+У4 (монеты 12 из 20)", int(d["всё"].sum()), "; и XRP не хуже", int((d["всё"]&d["XRP_ok"]).sum()))
d["балл"] = d["BTC_о"]+d["ETH_о"]+d["XRP_о"]
cols = ["шорт","лонг","пауза","размер","BTC_n","BTC_итог","BTC_просадка","BTC_с2025","BTC_p1","BTC_p2","BTC_p3","ETH_итог","ETH_просадка","ETH_с2025","XRP_итог","XRP_просадка","XRP_с2025","Bitstamp_итог","Bitstamp_просадка","монеты_итог","монеты_лучше","монеты_дд","монеты_с2025"]
print("\n=== все условия, лучшие по сумме отношений\n", d[d["всё"]].sort_values("балл",ascending=False).head(25)[cols].to_string(index=False))
print("\n=== только постоянный размер (без размера)\n", d[(d["размер"]=="постоянный")].sort_values("балл",ascending=False).head(14)[cols].to_string(index=False))
print("\n=== главные эффекты: средний прирост к базе по одному параметру, по всем комбинациям")
for f in ("шорт","лонг","пауза","размер"):
    g = d.groupby(f)[["BTC_итог","BTC_просадка","BTC_с2025","ETH_итог","ETH_просадка","ETH_с2025","XRP_итог","XRP_просадка","XRP_с2025","Bitstamp_итог","Bitstamp_просадка","монеты_итог","монеты_лучше","балл"]].mean().round(1).sort_values("балл",ascending=False)
    print(g.to_string()); print()
d.to_csv(OUT/"fam_z_scored.csv",index=False)
