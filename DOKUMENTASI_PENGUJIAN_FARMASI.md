# Dokumentasi Teknis API Modul Farmasi & Mutasi Stok Puskesmas

Dokumen ini berisi spesifikasi teknis endpoint REST API instalasi farmasi Puskesmas untuk modul E-Resep dan Manajemen Inventori Obat.

Base URL: `http://127.0.0.1:8003/api/v1/farmasi`

---

## 1. GET /health
Mengecek status ketersediaan service API farmasi.

### Request
```http
GET /api/v1/farmasi/health HTTP/1.1
Host: 127.0.0.1:8003
```

### Response (200 OK)
```json
{
  "status": "UP",
  "service": "SIMPUS Farmasi & E-Resep API",
  "version": "1.0.0",
  "timestamp": "2026-09-12T02:44:32Z",
  "author": "Muhammad Rafli Aolia"
}
```

---

## 2. GET /resep?status=menunggu
Mengambil antrian resep obat elektronik yang dikirim oleh dokter dari poli periksa dan menunggu penelaahan apoteker.

### Query Parameters
- `status` (opsional): `menunggu`, `siap_dispense`, `selesai`, `ditolak`.

### Request
```http
GET /api/v1/farmasi/resep?status=menunggu HTTP/1.1
Host: 127.0.0.1:8003
```

### Response (200 OK)
```json
{
  "status": "success",
  "filter_status": "menunggu",
  "total": 3,
  "data": [
    {
      "id_resep": "RSP-20260912-001",
      "no_resep": "E-RSP/2026/09/001",
      "waktu_kirim": "2026-09-12T08:45:10Z",
      "id_kunjungan": "VISIT-2026-091201",
      "no_rm": "RM-2026-00451",
      "nama_pasien": "Budi Santoso",
      "usia_pasien": "35 tahun",
      "berat_badan_kg": 68.0,
      "riwayat_alergi": [],
      "ruang_periksa": "Poli Umum",
      "dokter_penulis": "dr. Siti Rahmawati, Sp.PD",
      "status": "menunggu",
      "items": [
        {
          "id_obat": "OBT-001",
          "nama_obat": "Paracetamol 500 mg Tablet",
          "jumlah": 10,
          "satuan": "Tablet",
          "signa": "3 x 1 tablet sesudah makan (prn demam/nyeri)",
          "catatan_khusus": "Bila panas > 38 C"
        },
        {
          "id_obat": "OBT-002",
          "nama_obat": "Amoxicillin 500 mg Kapsul",
          "jumlah": 15,
          "satuan": "Kapsul",
          "signa": "3 x 1 kapsul sesudah makan (habiskan)",
          "catatan_khusus": "Antibiotik wajib habis"
        }
      ]
    }
  ]
}
```

---

## 3. POST /resep/{id}/telaah
Verifikasi administratif, farmasetis, dan klinis oleh apoteker. Memeriksa kontraindikasi alergi secara otomatis.

### Path Parameter
- `id`: ID e-resep (contoh: `RSP-20260912-001`)

### Request Body
```json
{
  "apoteker": "Apt. Muhammad Fauzan, S.Farm.",
  "keputusan": "DISETUJUI",
  "telaah_administratif": {
    "keabsahan_resep": true,
    "kejelasan_tulisan_signa": true,
    "identitas_pasien_sesuai": true
  },
  "telaah_farmasetis": {
    "bentuk_sediaan_tepat": true,
    "dosis_dan_aturan_pakai_tepat": true,
    "stabilitas_obat_terjamin": true
  },
  "telaah_klinis": {
    "ketepatan_indikasi": true,
    "tidak_ada_duplikasi": true,
    "bebas_interaksi_obat_fatal": true
  },
  "catatan": "Kesesuaian dosis anak/dewasa dan interaksi obat aman. Resep disetujui untuk dispensing."
}
```

### Response (200 OK)
```json
{
  "status": "success",
  "message": "Resep RSP-20260912-001 berhasil ditelaah dengan keputusan: DISETUJUI.",
  "status_resep": "siap_dispense",
  "data": {
    "id_resep": "RSP-20260912-001",
    "status": "siap_dispense"
  }
}
```

### Response Peringatan Alergi Obat (422 Unprocessable Entity)
```json
{
  "status": "error",
  "error_type": "KONTRAINDIKASI_ALERGI",
  "message": "Peringatan Alergi Obat: Pasien memiliki riwayat alergi terhadap obat yang diresepkan!",
  "detail_alergi": [
    {
      "id_obat": "OBT-002",
      "nama_obat": "Amoxicillin 500 mg Kapsul",
      "alergen": "Amoxicillin"
    }
  ],
  "rekomendasi": "Lakukan konfirmasi kembali ke dokter penulis resep atau tolak resep secara klinis."
}
```

---

## 4. POST /resep/{id}/dispense
Eksekusi penyiapan obat dan pemotongan stok otomatis real-time ke kartu inventori.

### Path Parameter
- `id`: ID e-resep (contoh: `RSP-20260912-001`)

### Request Body
```json
{
  "petugas_dispense": "Apt. Muhammad Fauzan, S.Farm."
}
```

### Response Berhasil (200 OK)
```json
{
  "status": "success",
  "message": "Resep RSP-20260912-001 berhasil didispense. Stok inventori terpotong otomatis secara real-time.",
  "status_resep": "selesai",
  "kondisi_stok": {
    "sebelum_dispense": {
      "OBT-001": 100,
      "OBT-002": 50
    },
    "sesudah_dispense": {
      "OBT-001": 90,
      "OBT-002": 35
    }
  },
  "dispense_summary": {
    "waktu_dispense": "2026-09-12T02:44:32Z",
    "petugas_dispense": "Apt. Muhammad Fauzan, S.Farm.",
    "total_item_obat": 2,
    "rincian_pemotongan": [
      {
        "id_obat": "OBT-001",
        "nama_obat": "Paracetamol 500 mg Tablet",
        "jumlah_keluar": 10,
        "stok_sebelum": 100,
        "stok_sesudah": 90
      },
      {
        "id_obat": "OBT-002",
        "nama_obat": "Amoxicillin 500 mg Kapsul",
        "jumlah_keluar": 15,
        "stok_sebelum": 50,
        "stok_sesudah": 35
      }
    ]
  }
}
```

### Response Proteksi Stok Kosong (422 Negative Stock Protection)
```json
{
  "status": "error",
  "error_type": "NEGATIVE_STOCK_PROTECTION",
  "message": "Dispensing dibatalkan! Stok obat tidak mencukupi, sistem mencegah mutasi stok negatif.",
  "detail_defisit": [
    {
      "id_obat": "OBT-004",
      "nama_obat": "Oralit Serbuk Sachet",
      "stok_tersedia": 5,
      "stok_diminta": 20,
      "defisit": 15,
      "alasan": "Kuantitas stok tidak mencukupi (Negative Stock Protection terpicu)."
    }
  ]
}
```

### Response Double Dispensing (409 Conflict)
```json
{
  "status": "error",
  "error_type": "ALREADY_DISPENSED",
  "message": "Resep RSP-20260912-001 sudah berstatus 'selesai' didispense sebelumnya. Double dispensing dicegah!"
}
```

---

## 5. GET /obat/{id}/kartu-stok
Melihat audit log pergerakan/mutasi stok obat tertentu.

### Response (200 OK)
```json
{
  "status": "success",
  "id_obat": "OBT-001",
  "nama_obat": "Paracetamol 500 mg Tablet",
  "stok_saat_ini": 90,
  "total_mutasi": 2,
  "data": [
    {
      "id_mutasi": "MUT-INIT-001",
      "id_obat": "OBT-001",
      "waktu": "2026-09-01T08:00:00Z",
      "jenis_mutasi": "SALDO_AWAL",
      "jumlah": 100,
      "stok_awal": 0,
      "stok_akhir": 100,
      "referensi": "INVENTORI-OPNAME-SEPT-2026"
    },
    {
      "id_mutasi": "MUT-20260912094432-001",
      "id_obat": "OBT-001",
      "nama_obat": "Paracetamol 500 mg Tablet",
      "waktu": "2026-09-12T02:44:32Z",
      "jenis_mutasi": "KELUAR_DISPENSING",
      "jumlah": 10,
      "stok_awal": 100,
      "stok_akhir": 90,
      "referensi": "E-RSP/2026/09/001",
      "id_resep": "RSP-20260912-001",
      "petugas": "Apt. Muhammad Fauzan, S.Farm.",
      "keterangan": "Pengeluaran obat pasien Budi Santoso (No RM: RM-2026-00451)"
    }
  ]
}
```
