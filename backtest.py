"""Backtest jujur untuk mode Santai.

Aturan simulasi (sengaja konservatif):
- Sinyal dinilai pada penutupan hari H. Masuk di harga BUKA hari H+1.
  Dilewati bila harga buka sudah lari > 1,5% di atas Entry rencana, atau sudah di bawah SL.
- Jika SL dan TP tersentuh di hari yang sama, dianggap SL lebih dulu.
- TP1: jual separuh, SL sisa pindah ke harga masuk. TP2: jual sisanya.
- Maksimal ditahan valid_days hari bursa, lalu keluar di harga tutup.
- Biaya: beli 0,15% + jual 0,25% (sudah termasuk pajak jual). Satu posisi per saham.
"""
import numpy as np
import pandas as pd
from engine import CFG, make_plan

FEE_BUY, FEE_SELL = 0.0015, 0.0025


def simulate(df, sc, min_score, cfg=CFG, start=None, end=None):
    trades = []
    n = len(df)
    idx = df.index
    o, h, l, c = (df[x].values for x in ("open", "high", "low", "close"))
    blocked_until = -1
    for i in range(cfg["warmup"], n - 1):
        if i <= blocked_until:
            continue
        r = sc.iloc[i]
        if not r["ok"] or r["total"] < min_score:
            continue
        if (start is not None and idx[i] < start) or (end is not None and idx[i] > end):
            continue
        p = make_plan(r["close"], r["atr"], r["support"], cfg)
        j = i + 1
        fill = o[j]
        if fill > p["entry"] * 1.015 or fill <= p["sl"]:
            continue
        risk_pct = (fill - p["sl"]) / fill
        remaining, gross, sl_cur, tp1_hit, outcome = 1.0, 0.0, p["sl"], False, None
        last = min(j + cfg["valid_days"] - 1, n - 1)
        exit_i = last
        for t in range(j, last + 1):
            if o[t] <= sl_cur:
                gross += remaining * (o[t] / fill - 1); outcome = "BE" if tp1_hit else "SL"; remaining = 0; exit_i = t; break
            if l[t] <= sl_cur:
                gross += remaining * (sl_cur / fill - 1); outcome = "BE" if tp1_hit else "SL"; remaining = 0; exit_i = t; break
            if not tp1_hit and h[t] >= p["tp1"]:
                px = max(o[t], p["tp1"])
                gross += 0.5 * (px / fill - 1); remaining = 0.5; tp1_hit = True; sl_cur = max(sl_cur, fill)
            if tp1_hit and h[t] >= p["tp2"]:
                px = max(o[t], p["tp2"])
                gross += remaining * (px / fill - 1); remaining = 0; outcome = "TP2"; exit_i = t; break
        if remaining > 0 and j + cfg["valid_days"] - 1 > n - 1:
            continue                  # transaksi masih berjalan di ujung data: belum dihitung
        if remaining > 0:
            gross += remaining * (c[last] / fill - 1)
            outcome = "TP1" if tp1_hit else "Kedaluwarsa"
            exit_i = last
        if outcome == "BE":
            outcome = "TP1"           # TP1 tercapai lalu sisa keluar di titik impas
        net = gross - FEE_BUY - FEE_SELL
        trades.append(dict(entry_date=str(idx[j].date()), exit_date=str(idx[exit_i].date()),
                           score=int(r["total"]), net=net, R=net / risk_pct,
                           outcome=outcome, bars=exit_i - j + 1))
        blocked_until = exit_i
    return trades


def stats(trades, risk_per_trade=0.01):
    if not trades:
        return dict(n=0)
    t = pd.DataFrame(trades).sort_values("exit_date")
    win, loss = t[t.net > 0], t[t.net <= 0]
    eq = (1 + risk_per_trade * t.R).cumprod()
    dd = (eq / eq.cummax() - 1).min()
    gl = -loss.net.sum()
    return dict(
        n=int(len(t)),
        win_rate=round(float(len(win) / len(t) * 100), 1),
        avg_win=round(float(win.net.mean() * 100), 2) if len(win) else 0.0,
        avg_loss=round(float(loss.net.mean() * 100), 2) if len(loss) else 0.0,
        expectancy=round(float(t.net.mean() * 100), 2),
        avg_R=round(float(t.R.mean()), 2),
        profit_factor=round(float(win.net.sum() / gl), 2) if gl > 0 else None,
        max_drawdown=round(float(dd * 100), 1),
        avg_hold=round(float(t.bars.mean()), 1),
        total_return_1pct=round(float((eq.iloc[-1] - 1) * 100), 1),
    )


def run_backtest(universe, cfg=CFG):
    """universe: {kode: (df, sc)}. Mengembalikan ringkasan untuk file backtest.json."""
    all_dates = sorted({d for df, sc in universe.values() for d in df.index[cfg["warmup"]:]})
    if len(all_dates) < 60:
        return dict(ready=False)
    cut = all_dates[int(len(all_dates) * 0.6)]
    start, end = all_dates[0], all_dates[-1]

    def collect(min_score, a=None, b=None):
        out = []
        for code, (df, sc) in universe.items():
            for tr in simulate(df, sc, min_score, cfg, a, b):
                tr["k"] = code
                out.append(tr)
        return out

    res = dict(ready=True, period=[str(start.date()), str(end.date())], split_date=str(cut.date()),
               fees=dict(buy=FEE_BUY, sell=FEE_SELL))
    main = collect(cfg["min_score"])
    res["overall"] = stats(main)
    res["in_sample"] = stats(collect(cfg["min_score"], start, cut))
    res["out_of_sample"] = stats(collect(cfg["min_score"], cut, end))
    res["by_threshold"] = {str(th): stats(collect(th)) for th in (60, 70, 80)}
    last = sorted(main, key=lambda x: x["exit_date"], reverse=True)[:25]
    res["recent"] = [dict(k=t["k"], tgl=t["exit_date"], hasil=t["outcome"], pct=round(t["net"] * 100, 1)) for t in last]
    return res
