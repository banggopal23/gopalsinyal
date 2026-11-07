"""Ekspor data harga harian banyak saham IDX (10 tahun) ke docs/prices.zip. Dijalankan lewat GitHub Actions."""
import io, os, sys, time, zipfile
import pandas as pd
import yfinance as yf

KODE = """
AALI ABMM ACES ADHI ADMR ADRO AGII AKRA AMMN AMRT ANTM APIC ARNA ARTO ASII ASRI AUTO AVIA BBCA BBHI BBKP BBNI BBRI BBTN BBYB BDMN BEST BFIN BGTG BIRD BISI BJBR BJTM BKSL BMAS BMRI BMTR BNGA BNII BNLI BOGA BREN BRIS BRMS BRPT BSDE BSSR BTPS BUKA BUMI BYAN CASA CLEO CMNP CMRY CPIN CPRO CTRA CUAN DEWA DGNS DILD DKFT DMAS DOID DSNG DSSA DUTI DVLA EAST ELSA EMTK ENRG ERAA ESSA EXCL FAST FILM FISH FREN GGRM GJTL GOTO GEMS GMFI GOOD GWSA HEAL HEXA HMSP HOKI HRTA HRUM IBST ICBP IMAS INAF INCO INDF INDY INKP INPC INTP IPCC IPCM ISAT ITMG JIHD JPFA JRPT JSMR JSPT KAEF KBLI KBLM KEEN KIJA KLBF KPIG LINK LPCK LPGI LPKR LPPF LSIP MAIN MAPA MAPI MARK MAYA MBMA MBSS MCAS MDKA MDLN MEDC MEGA MIDI MIKA MKPI MLBI MLPL MNCN MPMX MPPA MTDL MTEL MYOR NCKL NELY NFCX NISP NOBU OCAP PALM PANI PBID PGAS PGEO PGUN PJAA PNBN PNLF PNIN POWR PPRE PSAB PSSI PTBA PTPP PTRO PWON RAJA RALS RDTX RELI RICY ROTI SAME SCCO SCMA SGER SIDO SILO SIMP SINI SMAR SMBR SMCB SMDR SMGR SMMA SMRA SMSM SOCI SOHO SRIL SRTG SSIA SSMS STAA STTP SULI TAPG TBIG TBLA TCID TGKA TINS TKIM TLKM TMAS TOBA TOTL TOWR TPIA TRAM TRIM TRIS TRST TSPC TURI ULTJ UNIC UNTR UNVR VICI VIVA WEGE WIKA WINS WOOD WSBP WSKT WTON YELO ZINC
AGRO AHAP AISA AKPI AMAG ANJT APLN ASSA BABP BACA BAPA BCAP BCIC BEKS BHIT BIPI BKDP BLTZ BMSR BNBA BNBR BOLT BRAM BSIM BTEL BTON BULL BVIC CAMP CARS CEKA CFIN CINT CITA CNKO COWL CSAP DART DEFI DEPO DIGI DNET DPNS DYAN ECII EKAD ELTY EPMT ERTX ESTI FASW FMII FORU FPNI GAMA GDST GDYR GEMA GIAA GMTD GOLD GPRA GSMF GTBO HDFA HERO HITS IATA IGAR IIKP IKAI INAI INDR INDS INTA IPOL ISSP JKON JTPE KDSI KINO KMTR KOIN KONI KRAS LAPD LCGP LEAD LION LMAS LMPI LPIN MASA MCOL MDIA MFIN MFMI MGNA MICE MINA MITI MLIA MMLP MOLI MPRO MRAT MREI MTFN MTSM NIKL NIRO NRCA OKAS OMRE PADI PBRX PCAR PEGE PICO PLIN POLA POLU POLY PORT PRAS PRDA PSDN PTSN PURI PYFA RBMS RIMO RODA RUIS SDMU SDPC SFAN SHID SIPD SKBM SKLT SKRN SMDM SMRU SMSM SPMA SQMI SSTM TALF TARA TBMS TFCO TIRA TIRT TMPO TRUS UANG UNIT VOKS WAPO WICO WIIM WMUU ZBRA
""".split()
daftar_kode = sorted(set(KODE))


def tarik(sym):
    h = yf.Ticker(sym).history(period="10y", interval="1d", auto_adjust=False, actions=False)
    if h is None or h.empty:
        raise RuntimeError("kosong")
    h = h.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]].dropna(subset=["close"])
    idx = pd.to_datetime(h.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    h.index = idx.normalize()
    return h[~h.index.duplicated(keep="last")]


def main():
    frames, gagal = [], []
    daftar = [("IHSG", "^JKSE")] + [(k, k + ".JK") for k in daftar_kode]
    for n, (kode, sym) in enumerate(daftar, 1):
        ok = False
        for _ in range(2):
            try:
                h = tarik(sym)
                h.insert(0, "kode", kode)
                h.index.name = "tanggal"
                frames.append(h.reset_index())
                ok = True
                break
            except Exception:
                time.sleep(2)
        if not ok:
            gagal.append(kode)
        if n % 25 == 0:
            print(f"{n}/{len(daftar)} diproses, berhasil {len(frames)}", flush=True)
        time.sleep(0.4)
    if len(frames) < 50:
        sys.exit("Terlalu sedikit data berhasil diunduh. Tidak ada file yang ditulis.")
    df = pd.concat(frames, ignore_index=True)
    buf = io.StringIO()
    df.to_csv(buf, index=False, float_format="%.4f")
    os.makedirs("docs", exist_ok=True)
    with zipfile.ZipFile("docs/prices.zip", "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("prices.csv", buf.getvalue())
    print(f"Selesai: {df.kode.nunique()} kode, {len(df)} baris, {df.tanggal.min()} s/d {df.tanggal.max()}")
    print("Gagal diunduh:", len(gagal), *gagal[:80])


if __name__ == "__main__":
    main()
