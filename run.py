"""Pembaruan harian: tarik data -> hitung skor -> sinyal hari ini -> backtest -> tulis JSON untuk web app.

Pemakaian:
    python run.py                 # data sungguhan dari Yahoo Finance (kode .JK)
    python run.py --demo          # data buatan (hanya untuk uji coba, BUKAN data pasar)
    python run.py --out folder    # simpan hasil ke folder lain (bawaan: docs)
"""
import argparse, datetime as dt, json, os, sys, time

import numpy as np
import pandas as pd
import requests

from backtest import run_backtest
from engine import CFG, compute, explain, make_plan
import arena

HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"}


def load_tickers(path="tickers.txt"):
    out = {}
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#"):
            code, _, name = line.partition(",")
            out[code.strip().upper()] = name.strip() or code.strip().upper()
    return out


ERRORS = []


def _clean(df):
    df = df.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]].copy()
    idx = pd.to_datetime(df.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    df.index = idx.normalize()
    df = df[~df.index.duplicated(keep="last")].dropna(subset=["close", "open", "high", "low"])
    df["volume"] = df["volume"].fillna(0)
    return df


def fetch_yf(code):
    import yfinance as yf                      # lebih tahan dibatasi Yahoo daripada permintaan biasa
    h = yf.Ticker(code + ".JK").history(period="5y", interval="1d", auto_adjust=False, actions=False)
    if h is None or h.empty:
        raise RuntimeError("yfinance mengembalikan data kosong")
    return _clean(h)


def fetch_http(code):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{code}.JK"
    r = requests.get(url, params={"range": "5y", "interval": "1d"}, headers=HEADERS, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:120]!r}")
    res = r.json()["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    idx = pd.to_datetime(res["timestamp"], unit="s", utc=True).tz_convert("Asia/Jakarta")
    return _clean(pd.DataFrame({"open": q["open"], "high": q["high"], "low": q["low"],
                                "close": q["close"], "volume": q["volume"]}, index=idx))


def fetch(code, tries=2):
    for k in range(tries):
        for fn in (fetch_yf, fetch_http):
            try:
                return code, fn(code)
            except Exception as e:
                ERRORS.append(f"{code} [{fn.__name__}]: {type(e).__name__}: {str(e)[:160]}")
        time.sleep(3 * (k + 1))
    return code, None


def market_state():
    """Kondisi IHSG: di atas/bawah EMA 50 dan EMA 200. None bila data tidak bisa diunduh."""
    try:
        import yfinance as yf
        from engine import ema
        h = yf.Ticker("^JKSE").history(period="2y", interval="1d", auto_adjust=False, actions=False)
        c = _clean(h)["close"]
        if len(c) < 210:
            return None
        return dict(date=str(c.index[-1].date()), close=round(float(c.iloc[-1]), 1),
                    above50=bool(c.iloc[-1] > ema(c, 50).iloc[-1]), above200=bool(c.iloc[-1] > ema(c, 200).iloc[-1]))
    except Exception as e:
        ERRORS.append(f"IHSG: {type(e).__name__}: {str(e)[:120]}")
        return None


def demo_data(codes, n=1300, seed=7):
    """Data acak untuk menguji program. Bukan data pasar."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
    res = {}
    for code in codes:
        p0 = float(rng.choice([350, 900, 1800, 3200, 5200, 9000]))
        drift = rng.normal(0.0003, 0.0004, n // 150 + 1).repeat(150)[:n]
        ret = drift + rng.normal(0, 0.017, n)
        close = p0 * np.exp(np.cumsum(ret))
        opn = np.r_[close[0], close[:-1]] * (1 + rng.normal(0, 0.004, n))
        hi = np.maximum(opn, close) * (1 + np.abs(rng.normal(0, 0.007, n)))
        lo = np.minimum(opn, close) * (1 - np.abs(rng.normal(0, 0.007, n)))
        vol = np.exp(rng.normal(0, 0.5, n)) * 3e10 / close * (1 + 2 * (rng.random(n) < 0.05))
        res[code] = pd.DataFrame({"open": opn, "high": hi, "low": lo, "close": close, "volume": vol}, index=idx)
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--out", default="docs")
    a = ap.parse_args()
    names = load_tickers()
    codes = list(names)

    if a.demo:
        data = demo_data(codes)
    else:
        data, fails = {}, 0
        for i, c in enumerate(codes):
            code, df = fetch(c)
            if df is not None and len(df) > CFG["warmup"] + 60:
                data[code] = df
                fails = 0
            else:
                fails += 1
            if len(data) == 0 and fails >= 6:
                print("Enam saham pertama gagal semua. Contoh penyebab:")
                print("\n".join(ERRORS[:6]))
                sys.exit("Data tidak bisa diunduh dari server ini. Data lama dibiarkan.")
            time.sleep(0.4)
        print(f"Data berhasil: {len(data)} dari {len(codes)} saham")
        if ERRORS:
            print("Contoh kegagalan:", *ERRORS[:5], sep="\n  ")
        if len(data) < len(codes) * 0.5:
            sys.exit("Terlalu banyak saham gagal diunduh (kemungkinan Yahoo Finance membatasi akses). Data lama dibiarkan.")

    universe = {c: (df, compute(df)) for c, df in data.items()}
    latest = max(df.index[-1] for df, _ in universe.values())

    stocks, passed = [], 0
    for code, (df, sc) in universe.items():
        r = sc.iloc[-1]
        stale = (latest - df.index[-1]).days > 4          # tidak ada transaksi baru: curiga suspensi
        if not r["ok"] or stale:
            continue
        passed += 1
        if r["total"] < CFG["min_score"]:
            continue
        p = make_plan(r["close"], r["atr"], r["support"])
        prev = df["close"].iloc[-2]
        stocks.append(dict(k=code, nm=names[code], mode="santai", price=float(r["close"]),
                           chg=round(float((r["close"] / prev - 1) * 100), 2),
                           score=int(r["total"]), plan={k: float(v) for k, v in p.items()},
                           sig=explain(r)))
    stocks.sort(key=lambda s: -s["score"])

    wib = dt.datetime.now(dt.timezone(dt.timedelta(hours=7)))
    signals = dict(generated=wib.strftime("%Y-%m-%d %H:%M WIB"), last_data_date=str(latest.date()),
                   demo=a.demo, scanned=len(universe), passed_filter=passed, min_score=CFG["min_score"],
                   valid_days=CFG["valid_days"], stocks=stocks)
    market = None if a.demo else market_state()
    signals["market"] = market
    bt = run_backtest(universe)
    bt["demo"] = a.demo

    os.makedirs(a.out, exist_ok=True)
    json.dump(signals, open(os.path.join(a.out, "signals.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1, allow_nan=False)
    json.dump(bt, open(os.path.join(a.out, "backtest.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1, allow_nan=False)
    if not a.demo:
        try:
            print("Arena:", arena.update(os.path.join(a.out, "arena.json"), {c: d for c, (d, _) in universe.items()},
                                         names, stocks, str(latest.date()), market))
        except Exception as e:                      # arena tidak boleh menggagalkan pembaruan utama
            print("Arena gagal (diabaikan):", type(e).__name__, e)
    print(f"Sinyal hari ini: {len(stocks)} saham (dari {passed} yang lolos filter). Hasil ditulis ke folder '{a.out}'.")


if __name__ == "__main__":
    main()
