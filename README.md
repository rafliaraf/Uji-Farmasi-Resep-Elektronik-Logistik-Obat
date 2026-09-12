# Pengujian API Modul Farmasi & Mutasi Stok Puskesmas

Repo ini isinya hasil pengerjaan tugas pengujian endpoint penerimaan e-resep, telaah klinis apoteker, penyiapan obat (dispensing), dan pemotongan otomatis stok inventori di instalasi farmasi Puskesmas secara real-time dan bebas dari race condition.

- **Nama**: Muhammad Rafli Aolia
- **Tugas**: Verifikasi alur peresepan obat elektronik dan sinkronisasi mutasi stok Puskesmas
- **Hasil**: Semua skenario pengujian lulus (100% Passed)

---

### Apa Aja yang Diuji?

1. **Penerimaan Resep Masuk dari Ruang Periksa**
   - Uji endpoint `GET /resep?status=menunggu` untuk menarik daftar resep elektronik yang dikirim oleh dokter poli.
   - Resep memuat identitas pasien, usia, poli asal, dokter penulis, serta rincian obat dan aturan pakai (signa).

2. **Telaah & Verifikasi Resep Apoteker**
   - Uji `POST /resep/{id}/telaah` untuk verifikasi administratif, farmasetis, dan klinis.
   - Pengecekan riwayat alergi obat pasien otomatis: sistem langsung menolak resep jika dokter meresepkan obat yang alergi bagi pasien (**422 Unprocessable Entity**).

3. **Dispensing & Pemotongan Stok Otomatis**
   - Uji eksekusi `POST /resep/{id}/dispense` untuk penyiapan obat dan pemotongan kuantitas stok di tabel inventori secara real-time.
   - Seluruh mutasi pengeluaran obat otomatis tercatat ke kartu stok obat (`GET /obat/{id}/kartu-stok`).

4. **Proteksi Stok Kosong (Negative Stock Protection)**
   - Pengujian dispensing saat kuantitas obat yang diminta melebihi sisa stok fisik di inventori (contoh: permintaan 20 sachet Oralit saat stok hanya ada 5).
   - Sistem menolak transaksi (**422 Unprocessable Entity**), auto-rollback, dan menjamin stok tidak pernah minus.

5. **Proteksi Concurrency & Race Condition**
   - Pengujian multi-thread (5 request serentak) saat stok obat menipis (10 tablet Salbutamol).
   - Menggunakan mekanisme thread lock transaksional sehingga kuantitas stok tetap akurat, tidak over-dispense, dan tidak terjadi race condition.

---

### Ringkasan Test Case

| No | Modul | Skenario Pengujian | Expected | Hasil |
|:--:|---|---|:---:|:---:|
| 1 | Service | Health check service Farmasi | 200 OK | **PASS** |
| 2 | Resep | Tarik daftar e-resep masuk (status=menunggu) | 200 OK & data resep muncul | **PASS** |
| 3 | Telaah | Deteksi kontraindikasi alergi obat pasien | 422 Unprocessable Entity | **PASS** |
| 4 | Telaah | Telaah administratif, farmasetis, & klinis apoteker | 200 OK & status siap_dispense | **PASS** |
| 5 | Proteksi | Cegah dispensing resep yang belum ditelaah | 422 Unprocessable Entity | **PASS** |
| 6 | Dispensing | Eksekusi dispense & pemotongan stok otomatis | 200 OK & stok berkurang akurat | **PASS** |
| 7 | Kartu Stok | Cek catatan audit trail mutasi keluar di kartu stok | 200 OK & data mutasi valid | **PASS** |
| 8 | Negative Stock | Proteksi stok kosong / defisit (mencegah stok minus) | 422 Unprocessable Entity & stok aman | **PASS** |
| 9 | Idempotensi | Tolak dispense ulang pada resep yang sudah selesai | 409 Conflict | **PASS** |
| 10 | Concurrency | Uji multi-thread serentak (Race condition safety) | 2 sukses, 3 ditolak, sisa stok pas 2 | **PASS** |

---

### Bukti Mutasi Stok (Sebelum vs Sesudah Dispensing)

Pengujian pada resep `RSP-20260912-001` (Pasien Budi Santoso):

**1. Kondisi Stok Sebelum Dispense:**
- `OBT-001` (Paracetamol 500 mg Tablet): **100 Tablet**
- `OBT-002` (Amoxicillin 500 mg Kapsul): **50 Kapsul**

**2. Eksekusi Dispensing Resep (`RSP-20260912-001`):**
- Permintaan: 10 tablet Paracetamol & 15 kapsul Amoxicillin.

**3. Kondisi Stok Sesudah Dispense:**
- `OBT-001` (Paracetamol 500 mg Tablet): **90 Tablet** (-10 Tablet, Akurat)
- `OBT-002` (Amoxicillin 500 mg Kapsul): **35 Kapsul** (-15 Kapsul, Akurat)

**4. Log Database Mutasi Stok (Tabel `inventori_obat`):**
```sql
-- Kondisi Sebelum Dispense
SELECT id_obat, nama_obat, stok FROM inventori_obat WHERE id_obat IN ('OBT-001', 'OBT-002');
+---------+----------------------------+------+
| id_obat | nama_obat                  | stok |
+---------+----------------------------+------+
| OBT-001 | Paracetamol 500 mg Tablet  |  100 |
| OBT-002 | Amoxicillin 500 mg Kapsul  |   50 |
+---------+----------------------------+------+

-- Kondisi Sesudah Dispense (Terpotong Otomatis Real-Time)
SELECT id_obat, nama_obat, stok FROM inventori_obat WHERE id_obat IN ('OBT-001', 'OBT-002');
+---------+----------------------------+------+
| id_obat | nama_obat                  | stok |
+---------+----------------------------+------+
| OBT-001 | Paracetamol 500 mg Tablet  |   90 | -- (-10 Tablet)
| OBT-002 | Amoxicillin 500 mg Kapsul  |   35 | -- (-15 Kapsul)
+---------+----------------------------+------+
```

**5. Log Database Kartu Stok (Tabel `kartu_stok_log` - Audit Trail):**
```sql
SELECT id_mutasi, id_obat, jenis_mutasi, jumlah, stok_awal, stok_akhir, referensi, petugas FROM kartu_stok_log WHERE referensi = 'E-RSP/2026/09/001';
+-----------------------+---------+-------------------+--------+-----------+------------+--------------------+-----------------------------+
| id_mutasi             | id_obat | jenis_mutasi      | jumlah | stok_awal | stok_akhir | referensi          | petugas                     |
+-----------------------+---------+-------------------+--------+-----------+------------+--------------------+-----------------------------+
| MUT-20260912101910-01 | OBT-001 | KELUAR_DISPENSING |     10 |       100 |         90 | E-RSP/2026/09/001  | Apt. Muhammad Fauzan, S.Farm|
| MUT-20260912101910-02 | OBT-002 | KELUAR_DISPENSING |     15 |        50 |         35 | E-RSP/2026/09/001  | Apt. Muhammad Fauzan, S.Farm|
+-----------------------+---------+-------------------+--------+-----------+------------+--------------------+-----------------------------+
```

---

### Isi File di Repo
- `Postman_Collection_Farmasi_Puskesmas.json` : Export collection Postman v2.1.0 lengkap dengan assertion otomatis.
- `server.py` : Server REST API Python untuk modul Farmasi Puskesmas.
- `test_runner.py` : Script Python pengujian otomatis via terminal.
- `README.md` : Dokumentasi laporan hasil pengujian dan bukti mutasi stok.

---

### Cara Menjalankan

1. Jalankan API Server:
```bash
python server.py
```

2. Jalankan Pengujian Otomatis:
```bash
python test_runner.py
```

3. Jalankan via Postman:
- Import `Postman_Collection_Farmasi_Puskesmas.json` ke Postman.
- Pastikan menggunakan **Desktop Agent**, lalu jalankan via Collection Runner.
