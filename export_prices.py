"""Simpan data harga semua saham ke satu file (docs/prices.zip) agar bisa diunduh dan dianalisis."""
import os, sys, time

import pandas as pd

from run import _clean, demo_data, fetch, load_tickers


def main():
    names = load_tickers()
    frames = []
    if "--demo" in sys.argv:
        data = demo_data(list(names))
        for code, df in data.items():
            d = df.copy(); d.insert(0, "kode", code); frames.append(d)
    else:
        for c in names:
            code, df = fetch(c)
            if df is not None and len(df) > 0:
                d = df.copy(); d.insert(0, "kode", code); frames.append(d)
            time.sleep(0.4)
        try:                                  # indeks IHSG untuk membaca kondisi pasar
            import yfinance as yf
            h = yf.Ticker("^JKSE").history(period="5y", interval="1d", auto_adjust=False, actions=False)
            d = _clean(h); d.insert(0, "kode", "IHSG"); frames.append(d)
        except Exception as e:
            print("IHSG gagal diunduh:", e)
    if len(frames) < len(names) * 0.5:
        sys.exit("Terlalu banyak saham gagal diunduh. File tidak dibuat.")
    out = pd.concat(frames)
    out.index.name = "tanggal"
    os.makedirs("docs", exist_ok=True)
    out.round(2).to_csv("docs/prices.zip", compression={"method": "zip", "archive_name": "prices.csv"})
    print(f"Selesai: {len(frames)} instrumen, {len(out)} baris.")


if __name__ == "__main__":
    main()
