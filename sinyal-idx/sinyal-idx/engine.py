"""Mesin sinyal mode SANTAI (swing 1-4 minggu), data harian.

Semua perhitungan hanya memakai data sampai bar yang dinilai (tanpa mengintip masa depan),
sehingga hasil backtest memakai rumus yang sama persis dengan sinyal hari ini.
"""
import numpy as np
import pandas as pd

CFG = dict(
    min_value_idr=5e9,    # rata-rata nilai transaksi 20 hari minimal Rp 5 miliar
    min_price=100,        # buang saham gocap / harga sangat rendah
    max_atr_pct=8.0,      # buang saham terlalu liar (ATR > 8% harga)
    max_run10=35.0,       # buang yang sudah naik > 35% dalam 10 hari (rawan pompom)
    min_score=70,
    sl_atr=1.8, r1=2.0, r2=3.0,
    min_risk=0.025, max_risk=0.08,
    valid_days=20,
    k_pivot=5,
    warmup=200,
)

MAXPTS = {"Tren naik": 20, "Akumulasi": 25, "Harmonic": 15,
          "Dekat support": 10, "Momentum": 15, "Likuiditas": 15}


# ---------- Fraksi harga IDX ----------
def tick(p):
    return 1 if p < 200 else 2 if p < 500 else 5 if p < 2000 else 10 if p < 5000 else 25


def snap(v, mode="near"):
    t = tick(v)
    q = v / t
    q = np.floor(q) if mode == "down" else np.ceil(q) if mode == "up" else np.round(q)
    return float(q * t)


# ---------- Indikator ----------
def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def wilder(s, n):
    return s.ewm(alpha=1 / n, adjust=False).mean()


def rsi(c, n=14):
    d = c.diff()
    up, dn = d.clip(lower=0), -d.clip(upper=0)
    rs = wilder(up, n) / wilder(dn, n).replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(100)


def atr_adx(df, n=14):
    h, l, c = df["high"], df["low"], df["close"]
    pc = c.shift()
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    atr = wilder(tr, n)
    up, dn = h.diff(), -l.diff()
    pdm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=df.index)
    mdm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=df.index)
    pdi = 100 * wilder(pdm, n) / atr
    mdi = 100 * wilder(mdm, n) / atr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return atr, wilder(dx.fillna(0), n), pdi, mdi


# ---------- Pivot, support, harmonic (satu putaran, tanpa lookahead) ----------
PATTERNS = {  # nama: (ab_min, ab_max, xd_target, xd_toleransi)
    "Gartley": (0.558, 0.678, 0.786, 0.05),
    "Bat": (0.342, 0.54, 0.886, 0.04),
    "Butterfly": (0.726, 0.846, 1.272, 0.08),
    "Crab": (0.342, 0.678, 1.618, 0.08),
}


def match_bullish(piv, d_price, d_idx):
    """Cek pola XABCD bullish dengan titik D = harga sekarang. piv = pivot terakhir (L,H,L,H)."""
    (xi, x, _), (ai, a, _), (bi, b, _), (ci, cc, _) = piv[-4:]
    xa = a - x
    if xa <= 0 or not (b < a and cc > b and cc < a):
        return None
    ab = (a - b) / xa
    bc = (cc - b) / (a - b)
    if not (0.33 <= bc <= 0.94) or d_price >= cc or d_idx - ci > 15:
        return None
    xd = (a - d_price) / xa
    for name, (lo, hi, tgt, tol) in PATTERNS.items():
        if lo <= ab <= hi and abs(xd - tgt) <= tol:
            return name
    return None


def pivot_features(df, k):
    h, l, c, o = (df[x].values for x in ("high", "low", "close", "open"))
    n = len(df)
    piv = []  # (idx, harga, tipe)  tipe 'L'/'H', selalu bergantian
    support = np.full(n, np.nan)
    harm = np.full(n, None, dtype=object)
    for i in range(2 * k, n):
        p = i - k
        new = None
        if h[p] == h[p - k:i + 1].max():
            new = (p, h[p], "H")
        elif l[p] == l[p - k:i + 1].min():
            new = (p, l[p], "L")
        if new:
            if piv and piv[-1][2] == new[2]:
                if (new[2] == "H" and new[1] >= piv[-1][1]) or (new[2] == "L" and new[1] <= piv[-1][1]):
                    piv[-1] = new
            else:
                piv.append(new)
        lows = [q[1] for q in piv[-8:] if q[2] == "L" and q[1] < c[i]]
        if lows:
            support[i] = max(lows)
        if len(piv) >= 4 and piv[-4][2] == "L" and piv[-1][2] == "H":
            harm[i] = match_bullish(piv, l[i] if l[i] < c[i] else c[i], i)
    return support, harm


# ---------- Skor ----------
def compute(df, cfg=CFG):
    """df: kolom open, high, low, close, volume (indeks tanggal naik). Mengembalikan tabel skor per bar."""
    df = df.copy()
    c, h, l, o, v = df["close"], df["high"], df["low"], df["open"], df["volume"]
    atr, adx, pdi, mdi = atr_adx(df)
    e50, e200 = ema(c, 50), ema(c, 200)

    # 1) Tren (20)
    tren = (c > e50) * 8 + (e50 > e200) * 6 + (e50 > e50.shift(10)) * 6

    # 2) Akumulasi (25): volume di hari naik, posisi close dalam range, OBV
    upvol = (v * (c > c.shift())).rolling(10).sum() / v.rolling(10).sum().replace(0, np.nan)
    a1 = ((upvol - 0.5) / 0.25).clip(0, 1) * 10
    clv = (((c - l) - (h - c)) / (h - l).replace(0, np.nan)).fillna(0)
    a2 = (clv.rolling(10).mean() / 0.4).clip(0, 1) * 8
    obv = (np.sign(c.diff()).fillna(0) * v).cumsum()
    a3 = (obv > obv.rolling(20).mean()) * 7
    akum = a1.fillna(0) + a2.fillna(0) + a3

    # 3) Harmonic (15) dan 4) Dekat support (10)
    support, harm = pivot_features(df, cfg["k_pivot"])
    support = pd.Series(support, index=df.index)
    harm = pd.Series(harm, index=df.index)
    hp = pd.Series(np.where(harm.notna(), np.where(c > o, 15, 10), 0), index=df.index)
    d_sup = (c - support) / atr
    sup = (((5 - d_sup) / 3.5).clip(0, 1) * 10).fillna(0)

    # 5) Momentum (15): ADX searah + RSI di zona sehat
    mom = ((adx - 20) / 10).clip(0, 1) * 7 * (pdi > mdi) + (1 - (rsi(c) - 57).abs() / 18).clip(0, 1) * 8

    # 6) Likuiditas (15): nilai transaksi rata-rata 20 hari (Rp 5 M = 0, Rp 50 M = penuh)
    val20 = (c * v).rolling(20).mean()
    liq = ((np.log10(val20.clip(lower=1)) - np.log10(5e9)) / (np.log10(50e9) - np.log10(5e9))).clip(0, 1) * 15

    out = pd.DataFrame({
        "close": c, "open": o, "high": h, "low": l, "atr": atr, "support": support, "harm": harm,
        "adx": adx, "rsi": rsi(c), "val20": val20, "upvol": upvol,
        "Tren naik": tren, "Akumulasi": akum, "Harmonic": hp,
        "Dekat support": sup, "Momentum": mom, "Likuiditas": liq,
    }, index=df.index)
    out["obv_up"] = obv > obv.rolling(20).mean()
    out["f_e50"], out["f_gold"], out["f_slope"] = c > e50, e50 > e200, e50 > e50.shift(10)
    out["total"] = out[list(MAXPTS)].sum(axis=1).round()

    # Filter keselamatan (wajib lolos, apa pun skornya)
    run10 = (c / c.shift(10) - 1) * 100
    ok = ((val20 >= cfg["min_value_idr"]) & (c >= cfg["min_price"]) &
          (atr / c * 100 <= cfg["max_atr_pct"]) & (run10 <= cfg["max_run10"]) &
          (v.rolling(10).min() > 0))
    ok.iloc[:cfg["warmup"]] = False
    out["ok"] = ok.fillna(False)
    return out


# ---------- Rencana trading ----------
def make_plan(close, atr_v, support, cfg=CFG):
    entry = snap(close)
    sl = entry - cfg["sl_atr"] * atr_v
    if support == support and 0.8 * atr_v <= entry - support <= 2.5 * atr_v:
        sl = support - 0.3 * atr_v                       # di bawah support terdekat
    rp = min(max((entry - sl) / entry, cfg["min_risk"]), cfg["max_risk"])
    sl = snap(entry * (1 - rp), "down")
    if sl >= entry:
        sl = entry - tick(entry)
    risk = entry - sl
    return dict(entry=entry, sl=sl,
                tp1=snap(entry + cfg["r1"] * risk, "up"),
                tp2=snap(entry + cfg["r2"] * risk, "up"), risk=risk)


def explain(row):
    """Daftar alasan sinyal untuk satu bar (dalam bahasa Indonesia)."""
    tr = [t for t, f in (("harga di atas EMA 50", row["f_e50"]),
                         ("EMA 50 di atas EMA 200", row["f_gold"]),
                         ("EMA 50 menanjak", row["f_slope"])) if f]
    notes = {
        "Tren naik": ((lambda t: t[0].upper() + t[1:])(", ".join(tr)) if tr else "Tren belum naik"),
        "Akumulasi": (f"{row['upvol']*100:.0f}% volume 10 hari terjadi di hari naik"
                      + (", OBV di atas rata-rata" if row["obv_up"] else "")) if row["upvol"] == row["upvol"] else "Data volume kurang",
        "Harmonic": f"Pola {row['harm']} bullish, harga di zona D" if row["harm"] else "Tidak ada pola terdeteksi",
        "Dekat support": (f"{(row['close']-row['support'])/row['atr']:.1f}".replace(".", ",") + f"x ATR di atas support {num(row['support'])}"
                          if row["support"] == row["support"] else "Support terdekat belum jelas"),
        "Momentum": f"ADX {row['adx']:.0f}, RSI {row['rsi']:.0f}",
        "Likuiditas": f"Transaksi rata-rata Rp {row['val20']/1e9:.0f} M per hari",
    }
    return [dict(n=k, p=int(round(row[k])), m=m, t=notes[k]) for k, m in MAXPTS.items()]


def num(v):
    return f"{v:,.0f}".replace(",", ".")
