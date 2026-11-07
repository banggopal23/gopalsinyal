"""Pembaruan harian: tarik data -> hitung skor -> sinyal hari ini -> backtest -> tulis JSON untuk web app.

Pemakaian:
    python run.py                 # data sungguhan dari Yahoo Finance (kode .JK)
    python run.py --demo          # data buatan (hanya untuk uji coba, BUKAN data pasar)
    python run.py --out folder    # simpan hasil ke folder lain (bawaan: docs)
"""
import argparse, datetime as dt, json, os, sys, time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
import requests

from backtest import run_backtest
from engine import CFG, compute, explain, make_plan

HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"}


def load_tickers(path="tickers.txt"):
    out = {}
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#"):
            code, _, name = line.partition(",")
            out[code.strip().upper()] = name.strip() or code.strip().upper()
    return out


def fetch(code, tries=3):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{code}.JK"
    for k in range(tries):
        try:
            r = requests.get(url, params={"range": "5y", "interval": "1d"}, headers=HEADERS, timeout=30)
            if r.status_code == 200:
                res = r.json()["chart"]["result"][0]
                q = res["indicators"]["quote"][0]
                idx = pd.to_datetime(res["timestamp"], unit="s", utc=True).tz_convert("Asia/Jakarta").tz_localize(None).normalize()
                df = pd.DataFrame({"open": q["open"], "high": q["high"], "low": q["low"],
                                   "close": q["close"], "volume": q["volume"]}, index=idx)
                df = df[~df.index.duplicated(keep="last")].dropna(subset=["close", "open", "high", "low"])
                df["volume"] = df["volume"].fillna(0)
                return code, df
        except Exception:
            pass
        time.sleep(2 * (k + 1))
    return code, None


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
        with ThreadPoolExecutor(max_workers=4) as ex:
            data = {c: d for c, d in ex.map(fetch, codes) if d is not None and len(d) > CFG["warmup"] + 60}
        failed = len(codes) - len(data)
        print(f"Data berhasil: {len(data)} dari {len(codes)} saham")
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
    bt = run_backtest(universe)
    bt["demo"] = a.demo

    os.makedirs(a.out, exist_ok=True)
    json.dump(signals, open(os.path.join(a.out, "signals.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1, allow_nan=False)
    json.dump(bt, open(os.path.join(a.out, "backtest.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1, allow_nan=False)
    print(f"Sinyal hari ini: {len(stocks)} saham (dari {passed} yang lolos filter). Hasil ditulis ke folder '{a.out}'.")


if __name__ == "__main__":
    main()
