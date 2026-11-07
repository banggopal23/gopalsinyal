# Gopal Sinyal (mode Santai)

Aplikasi web gratis yang tiap sore memindai saham IDX, memberi skor 0-100, lalu menampilkan
**Entry, SL, TP1, TP2** dan jumlah lot sesuai modal Anda. Dilengkapi hasil uji (backtest) supaya
Anda bisa menilai sendiri apakah aturannya layak dipercaya.

Anda tidak perlu menulis kode. Cukup ikuti langkah di bawah (sekitar 15 menit, sekali saja).

## Cara memasang

**1. Buat akun GitHub** (gratis) di https://github.com

**2. Buat repositori baru**
- Klik tanda **+** di kanan atas, lalu **New repository**.
- Nama: `sinyal-idx`. Pilih **Public**. Klik **Create repository**.

**3. Unggah semua file**
- Ekstrak file zip ini di komputer Anda.
- Di halaman repositori, klik **uploading an existing file**.
- Seret semua isi folder (termasuk folder `docs` dan `.github`) ke halaman itu, lalu klik **Commit changes**.
- Bila folder `.github` tidak ikut terunggah (karena tersembunyi): klik **Add file → Create new file**,
  isi nama file dengan `.github/workflows/update.yml`, tempel isi file `update.yml` dari zip,
  lalu **Commit changes**.

**4. Aktifkan halaman web**
- **Settings → Pages**. Di bagian *Branch*, pilih `main` dan folder `/docs`, lalu **Save**.
- Setelah 1-2 menit, alamat aplikasi Anda muncul di halaman itu
  (bentuknya `https://NAMAANDA.github.io/sinyal-idx/`).

**5. Izinkan pembaruan otomatis**
- **Settings → Actions → General → Workflow permissions**, pilih **Read and write permissions**, lalu **Save**.

**6. Jalankan pembaruan pertama**
- Buka tab **Actions → Pembaruan harian → Run workflow → Run workflow**.
- Tunggu 3-5 menit sampai ada tanda centang hijau, lalu buka alamat aplikasi Anda.

Setelah itu pembaruan berjalan **otomatis setiap hari bursa pukul 16:40 WIB**.
Bila suatu hari tidak jalan, tekan **Run workflow** lagi.

## Cara membaca aplikasi

- **Santai**: sinyal yang lolos (skor 70+ dan lolos filter keselamatan). Tidak ada sinyal di suatu hari itu normal.
- **Riwayat**: hasil simulasi aturan pada data historis, sudah dikurangi biaya beli 0,15% dan jual 0,25%.
  Dua tabel di sana yang paling penting:
  1. *Periode awal vs akhir*: apakah hasil bertahan di data yang tidak dipakai merancang aturan.
  2. *Skor 60+/70+/80+*: apakah skor lebih tinggi benar-benar lebih baik.
  Kalau profit factor (PF) di bawah 1 atau skor tinggi tidak lebih baik, jangan pakai uang sungguhan.
- **Cara pakai sinyal**: pasang order beli di sekitar Entry, langsung pasang SL, dan jual separuh di TP1.
  Setelah TP1 tercapai, geser SL sisanya ke harga beli. Sinyal berlaku sampai 20 hari bursa.
- **Kalkulator lot**: isi modal dan risiko per transaksi (disarankan 1%). Rugi maksimal per transaksi
  tidak lebih dari angka itu bila SL tereksekusi di harganya.

## Mengubah daftar saham

Buka `tickers.txt` di GitHub, klik ikon pensil, tambah atau hapus baris (format `KODE,Nama`, tanpa `.JK`), lalu Commit.

## Yang belum ada (jujur)

- Mode **Cepat** (Open = Low, lonjakan volume): menunggu mode Santai terbukti.
- **Deteksi bandar** memakai proksi dari harga dan volume (volume di hari naik, OBV, posisi penutupan).
  Data broker (siapa beli/jual) tidak tersedia gratis.
- **Fundamental** belum dipakai. Skor "Likuiditas" mengisi bobot itu sementara.
- Harmonic hanya pola **bullish** (Gartley, Bat, Butterfly, Crab). Tingkat sinyal palsunya tinggi,
  jadi bobotnya hanya 15 dari 100.
- Data dari Yahoo Finance: gratis tetapi tidak resmi, kadang terlambat atau bolong. Cek harga di aplikasi sekuritas sebelum membeli.
- Backtest belum memperhitungkan slippage, antrean beli, dan batas ARA/ARB.

## Saran sebelum pakai uang sungguhan

Pantau sinyalnya 1-2 bulan tanpa uang (paper trading), bandingkan dengan tabel Riwayat,
lalu mulai dengan modal kecil dan risiko 0,5-1% per transaksi.

*Alat bantu analisis, bukan nasihat investasi. Anda sendiri yang menanggung risiko keputusan Anda.*

## Isi folder

- `engine.py` : mesin skor dan rencana Entry/SL/TP
- `backtest.py` : simulasi historis dan statistiknya
- `run.py` : tarik data, jalankan semuanya, tulis hasil ke `docs/`
- `docs/index.html` : tampilan aplikasi (dibaca dari `signals.json` dan `backtest.json`)
- `tickers.txt` : daftar saham yang dipindai
- `.github/workflows/update.yml` : jadwal pembaruan harian
- Uji coba di komputer: `python run.py --demo --out demo` (data acak, hanya untuk mengecek program)
