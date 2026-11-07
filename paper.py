"""Uji maju (paper trading): setiap sinyal baru dicatat, lalu hasilnya dihitung dari harga nyata hari-hari berikutnya.

Tidak ada uang sungguhan. Aturannya sama persis dengan backtest (masuk di harga buka besok, SL lebih dulu
bila bentrok, TP1 jual separuh lalu SL ke titik masuk, maksimal ditahan valid_days hari, biaya 0,4%).
Catatan sinyal hanya bertambah (tidak pernah ditulis ulang), jadi hasilnya tidak bisa 'diperbaiki' belakangan.
"""
import json, os
import pandas as pd
from backtest import FEE_BUY, FEE_SELL
from engine import CFG


def play(df, sig_date, plan, cfg=CFG):
    """Hitung nasib satu sinyal. Mengembalikan dict status: menunggu | dilewati | berjalan | selesai."""
    idx = df.index
    pos = idx.get_indexer([pd.Timestamp(sig_date)])[0]
    if pos < 0:
        return dict(status="menunggu")
    j = pos + 1
    if j >= len(df):
        return dict(status="menunggu")
    o, h, l, c = (df[x].values for x in ("open", "high", "low", "close"))
    fill = float(o[j])
    if fill > plan["entry"] * 1.015 or fill <= plan["sl"]:
        return dict(status="dilewati", entry_date=str(idx[j].date()), fill=fill)
    rem, gross, sl_cur, tp1, outcome, exit_i = 1.0, 0.0, plan["sl"], False, None, None
    last = j + int(plan.get("days", cfg["valid_days"])) - 1
    for t in range(j, min(last, len(df) - 1) + 1):
        if o[t] <= sl_cur:
            gross += rem * (o[t] / fill - 1); outcome = "TP1" if tp1 else "SL"; rem = 0; exit_i = t; break
        if l[t] <= sl_cur:
            gross += rem * (sl_cur / fill - 1); outcome = "TP1" if tp1 else "SL"; rem = 0; exit_i = t; break
        if not tp1 and h[t] >= plan["tp1"]:
            gross += 0.5 * (max(o[t], plan["tp1"]) / fill - 1); rem = 0.5; tp1 = True; sl_cur = max(sl_cur, fill)
        if tp1 and h[t] >= plan["tp2"]:
            gross += rem * (max(o[t], plan["tp2"]) / fill - 1); rem = 0; outcome = "TP2"; exit_i = t; break
    if rem > 0:
        if last <= len(df) - 1:                       # masa berlaku habis: keluar di harga tutup
            gross += rem * (c[last] / fill - 1); outcome = "TP1" if tp1 else "Kedaluwarsa"; exit_i = last
        else:                                          # masih berjalan: nilai sementara
            mtm = gross + rem * (c[-1] / fill - 1)
            return dict(status="berjalan", entry_date=str(idx[j].date()), fill=fill, tp1_hit=tp1,
                        pct=round((mtm - FEE_BUY - FEE_SELL) * 100, 2), last=float(c[-1]))
    net = gross - FEE_BUY - FEE_SELL
    return dict(status="selesai", entry_date=str(idx[j].date()), exit_date=str(idx[exit_i].date()),
                fill=fill, outcome=outcome, pct=round(net * 100, 2))


def update(path, universe_df, signals, names, last_date):
    """universe_df: {kode: DataFrame}. signals: daftar saham sinyal hari ini. Menulis path (json)."""
    log = []
    if os.path.exists(path):
        try:
            log = json.load(open(path, encoding="utf-8")).get("log", [])
        except Exception:
            log = []
    have = {(x["k"], x["sig"]) for x in log}
    for s in signals:
        if (s["k"], last_date) not in have:
            log.append(dict(k=s["k"], nm=s["nm"], sig=last_date, score=s["score"], plan=s["plan"]))
    trades, busy = [], {}
    for x in sorted(log, key=lambda z: z["sig"]):
        df = universe_df.get(x["k"])
        res = play(df, x["sig"], x["plan"]) if df is not None else dict(status="menunggu")
        if res["status"] == "dilewati":
            pass
        elif x["k"] in busy and res.get("entry_date") and res["entry_date"] <= busy[x["k"]]:
            res = dict(status="dilewati")               # satu posisi per saham
        else:
            busy[x["k"]] = res.get("exit_date") or "9999-12-31"
        trades.append({**x, **res})
    done = [t for t in trades if t["status"] == "selesai"]
    wins = [t["pct"] for t in done if t["pct"] > 0]
    loss = [t["pct"] for t in done if t["pct"] <= 0]
    summ = dict(n_selesai=len(done), n_berjalan=sum(t["status"] == "berjalan" for t in trades),
                n_menunggu=sum(t["status"] == "menunggu" for t in trades),
                win_rate=round(100 * len(wins) / len(done), 1) if done else None,
                avg=round(sum(t["pct"] for t in done) / len(done), 2) if done else None,
                pf=round(sum(wins) / -sum(loss), 2) if loss and sum(loss) < 0 else None)
    json.dump(dict(started=min((x["sig"] for x in log), default=None), summary=summ, log=log, trades=trades[-60:][::-1]),
              open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1, allow_nan=False)
    return summ
