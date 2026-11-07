"""Arena strategi: beberapa strategi dicatat otomatis setiap hari (tanpa uang sungguhan), hasilnya dibandingkan
dengan pembanding acak. Semua aturan ditetapkan di muka dan catatan sinyal tidak pernah ditulis ulang.
"""
import json, os
import numpy as np
import pandas as pd
from engine import ema, rsi, atr_adx, snap
from paper import play

FEE = 0.004
LULUS = dict(min_selesai=30, min_pf=1.3)

INFO = {
    "santai": ("Santai (skor 70+)", "Tren naik + akumulasi + dekat support. Aturan yang sudah ada.", "Santai"),
    "pullback": ("Koreksi dalam tren naik (RSI<35)", "RSI14 di bawah 35 saat harga masih di atas EMA 200. SL 2 ATR, target 3 ATR, maks 10 hari.", "Koreksi"),
    "pullback30": ("Koreksi dalam (RSI<30)", "Versi lebih ketat: RSI14 di bawah 30 saat harga masih di atas EMA 200. Sinyal jarang tapi uji data lama paling menjanjikan.", "Koreksi30"),
    "momentum": ("Momentum 60 hari", "Saham yang baru masuk 10 terkuat (kenaikan 60 hari). Ditahan maks 20 hari.", "Momentum"),
    "ai": ("AI (gradient boosting)", "Model belajar dari riwayat harga dan dilatih ulang tiap hari; memilih 3 saham dengan peluang tertinggi.", "AI"),
    "acak": ("Pembanding acak", "3 saham likuid acak per hari. Strategi yang tidak mengalahkan ini berarti tidak punya keunggulan.", "Acak"),
}


def _feat(g):
    c, v = g["close"], g["volume"]
    atr, adx, _, _ = atr_adx(g)
    f = g.copy()
    f["atr"], f["adx"] = atr, adx
    f["ema20"], f["ema50"], f["ema200"] = ema(c, 20), ema(c, 50), ema(c, 200)
    f["rsi14"] = rsi(c, 14)
    for n in (3, 5, 20, 60):
        f[f"ret{n}"] = c / c.shift(n) - 1
    f["val20"] = (c * v).rolling(20).mean()
    f["volr"] = v / v.rolling(20).mean()
    f["liq"] = (f["val20"] >= 5e9) & (c >= 100)
    f["d_e20"], f["d_e50"], f["d_e200"] = c / f.ema20 - 1, c / f.ema50 - 1, c / f.ema200 - 1
    f["atrp"] = atr / c
    return f


def _plan(close, atr_v, sl_atr, tp_atr, days):
    entry = snap(close)
    sl = snap(entry - sl_atr * atr_v, "down")
    if sl >= entry:
        sl = entry - 1
    risk = entry - sl
    tp = snap(entry + tp_atr * atr_v, "up")
    return dict(entry=entry, sl=sl, tp1=tp, tp2=tp, risk=risk, days=days)


def _panel(feats, col):
    return pd.concat({k: f[col] for k, f in feats.items()}, axis=1)


def candidates(universe_df, names, santai, last_date, market=None):
    """Sinyal hari ini untuk tiap strategi. Mengembalikan {strategi: [ {k,nm,score?,plan} ]}."""
    feats = {k: _feat(df) for k, df in universe_df.items() if len(df) > 260}
    t = pd.Timestamp(last_date)
    now = {k: f.loc[t] for k, f in feats.items() if t in f.index and bool(f.loc[t, "liq"]) and pd.notna(f.loc[t, "atr"])}
    out = {"santai": [dict(k=s["k"], nm=s["nm"], plan={**s["plan"], "days": 20}) for s in santai]}

    for key, thr in (("pullback", 35), ("pullback30", 30)):
        pb = [k for k, r in now.items() if r.rsi14 < thr and r.close > r.ema200]
        out[key] = [dict(k=k, nm=names.get(k, k), plan=_plan(now[k].close, now[k].atr, 2.0, 3.0, 10)) for k in pb]

    r60 = _panel(feats, "ret60")
    liq = _panel(feats, "liq").fillna(False)
    r60l = r60.where(liq)
    top = r60l.rank(axis=1, ascending=False) <= 10
    if t in top.index:
        i = top.index.get_loc(t)
        new = [k for k in top.columns if top.iloc[i][k] and i > 0 and not top.iloc[i - 1][k] and k in now]
        out["momentum"] = []
        for k in new:
            r = now[k]
            p = _plan(r.close, r.atr, 2.5, 0, 20)
            p["tp1"] = p["tp2"] = snap(r.close * 1.5, "up")           # praktis hanya keluar karena waktu/SL
            out["momentum"].append(dict(k=k, nm=names.get(k, k), plan=p))

    rng = np.random.default_rng(int(t.strftime("%Y%m%d")))
    keys = sorted(now)
    pick = list(rng.choice(keys, size=min(3, len(keys)), replace=False)) if keys else []
    out["acak"] = [dict(k=k, nm=names.get(k, k), plan=_plan(now[k].close, now[k].atr, 2.0, 3.0, 10)) for k in pick]

    out["ai"] = _ai(feats, now, names, t)
    return out


def _ai(feats, now, names, t):
    try:
        from sklearn.ensemble import HistGradientBoostingClassifier as HGB
    except Exception:
        return []
    FF = ["ret3", "ret5", "ret20", "ret60", "rsi14", "adx", "volr", "d_e20", "d_e50", "d_e200", "atrp"]
    rows = []
    for k, f in feats.items():
        d = f[f.liq & f[FF].notna().all(axis=1)].copy()
        d["y"] = (f.open.shift(-11) / f.open.shift(-1) - 1 - FEE > 0).astype(float).where(f.open.shift(-11).notna()).reindex(d.index)
        d["k"] = k
        rows.append(d)
    X = pd.concat(rows)
    idx = sorted(X.index.unique())
    if t not in X.index:
        return []
    cut = idx[max(0, idx.index(t) - 12)]
    tr = X[(X.index < cut) & X.y.notna()]
    if len(tr) < 5000:
        return []
    m = HGB(max_depth=3, learning_rate=0.05, max_iter=150, l2_regularization=5.0, random_state=0).fit(tr[FF], tr.y)
    te = X.loc[[t]]
    te = te.assign(p=m.predict_proba(te[FF])[:, 1]).sort_values("p", ascending=False).head(3)
    return [dict(k=r.k, nm=names.get(r.k, r.k), prob=round(float(r.p), 3),
                 plan=_plan(now[r.k].close, now[r.k].atr, 2.0, 3.0, 10)) for r in te.itertuples() if r.k in now]


def _summ(trades):
    done = [x for x in trades if x["status"] == "selesai"]
    w = [x["pct"] for x in done if x["pct"] > 0]
    l = [x["pct"] for x in done if x["pct"] <= 0]
    return dict(n_selesai=len(done), n_berjalan=sum(x["status"] == "berjalan" for x in trades),
                n_menunggu=sum(x["status"] == "menunggu" for x in trades),
                win_rate=round(100 * len(w) / len(done), 1) if done else None,
                avg=round(sum(x["pct"] for x in done) / len(done), 2) if done else None,
                pf=round(sum(w) / -sum(l), 2) if l and sum(l) < 0 else None)


def update(path, universe_df, names, santai, last_date, market=None):
    old = {}
    if os.path.exists(path):
        try:
            old = json.load(open(path, encoding="utf-8"))
        except Exception:
            old = {}
    cand = candidates(universe_df, names, santai, last_date, market)
    res = {}
    for key, (label, desc, short) in INFO.items():
        log = old.get("strategies", {}).get(key, {}).get("log", [])
        have = {(x["k"], x["sig"]) for x in log}
        for s in cand.get(key, []):
            if (s["k"], last_date) not in have:
                log.append(dict(k=s["k"], nm=s["nm"], sig=last_date, plan=s["plan"], **({"prob": s["prob"]} if "prob" in s else {})))
        trades, busy = [], {}
        for x in sorted(log, key=lambda z: z["sig"]):
            df = universe_df.get(x["k"])
            r = play(df, x["sig"], x["plan"]) if df is not None else dict(status="menunggu")
            if r["status"] != "dilewati":
                if x["k"] in busy and r.get("entry_date") and r["entry_date"] <= busy[x["k"]]:
                    r = dict(status="dilewati")
                else:
                    busy[x["k"]] = r.get("exit_date") or "9999-12-31"
            trades.append({**x, **r})
        res[key] = dict(label=label, desc=desc, short=short, summary=_summ(trades), log=log,
                        today=cand.get(key, []), trades=[{k: v for k, v in x.items() if k != "plan"} for x in trades[-12:][::-1]])
    acak_pf = res["acak"]["summary"]["pf"]
    for key, v in res.items():
        m = v["summary"]
        if key == "acak":
            v["verdict"] = "pembanding"
        elif m["n_selesai"] < LULUS["min_selesai"]:
            v["verdict"] = "data"
        elif m["pf"] and m["pf"] >= LULUS["min_pf"] and m["avg"] > 0 and (acak_pf is None or m["pf"] > acak_pf):
            v["verdict"] = "lolos"
        else:
            v["verdict"] = "gagal"
    started = min((x["sig"] for v in res.values() for x in v["log"]), default=None)
    json.dump(dict(started=started, rules=LULUS, last_date=last_date, market=market, strategies=res),
              open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1, allow_nan=False, default=float)
    return {k: (v["verdict"], v["summary"]["n_selesai"]) for k, v in res.items()}
