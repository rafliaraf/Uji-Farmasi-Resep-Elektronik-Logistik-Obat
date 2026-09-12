"""
Mock API Server: Modul Farmasi & Mutasi Stok Inventori Puskesmas
Menguji alur e-resep:
- Penerimaan e-resep dari ruang periksa/dokter (GET /api/v1/farmasi/resep?status=menunggu)
- Telaah resep administratif & klinis apoteker (POST /api/v1/farmasi/resep/{id}/telaah)
- Dispensing obat & pemotongan stok otomatis real-time (POST /api/v1/farmasi/resep/{id}/dispense)
- Mutasi stok inventori & kartu stok (GET /api/v1/farmasi/obat, GET /api/v1/farmasi/obat/{id}/kartu-stok)
- Proteksi negative stock & anti-race-condition dengan Threading Lock & Atomic Transaction
"""

import json
import re
import threading
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# Thread lock untuk menjamin concurrency safety dan perlindungan race condition
DB_LOCK = threading.Lock()

# Data Master Obat Awal
INITIAL_OBAT = [
    {
        "id_obat": "OBT-001",
        "kode_kfa": "93001234",
        "nama_obat": "Paracetamol 500 mg Tablet",
        "satuan": "Tablet",
        "stok": 100,
        "stok_minimum": 20,
        "lokasi_rak": "RAK-A-01",
        "no_batch": "BATCH-PCT-2026A",
        "tgl_kadaluarsa": "2027-12-31"
    },
    {
        "id_obat": "OBT-002",
        "kode_kfa": "93005678",
        "nama_obat": "Amoxicillin 500 mg Kapsul",
        "satuan": "Kapsul",
        "stok": 50,
        "stok_minimum": 15,
        "lokasi_rak": "RAK-B-03",
        "no_batch": "BATCH-AMX-2026C",
        "tgl_kadaluarsa": "2027-08-15"
    },
    {
        "id_obat": "OBT-003",
        "kode_kfa": "93009012",
        "nama_obat": "Cetirizine 10 mg Tablet",
        "satuan": "Tablet",
        "stok": 30,
        "stok_minimum": 10,
        "lokasi_rak": "RAK-A-05",
        "no_batch": "BATCH-CTZ-2026B",
        "tgl_kadaluarsa": "2028-01-10"
    },
    {
        "id_obat": "OBT-004",
        "kode_kfa": "93004411",
        "nama_obat": "Oralit Serbuk Sachet",
        "satuan": "Sachet",
        "stok": 5,  # Stok menipis untuk pengujian negative stock / stok tidak cukup
        "stok_minimum": 10,
        "lokasi_rak": "RAK-C-02",
        "no_batch": "BATCH-ORL-2026D",
        "tgl_kadaluarsa": "2027-05-20"
    },
    {
        "id_obat": "OBT-005",
        "kode_kfa": "93007788",
        "nama_obat": "Salbutamol 2 mg Tablet (Stok Kritis Race-Condition)",
        "satuan": "Tablet",
        "stok": 10,  # Untuk simulasi concurrency test race condition
        "stok_minimum": 5,
        "lokasi_rak": "RAK-B-01",
        "no_batch": "BATCH-SLB-2026X",
        "tgl_kadaluarsa": "2027-11-30"
    }
]

# Kartu Stok (Audit Log Mutasi Obat)
INITIAL_MUTASI = [
    {
        "id_mutasi": "MUT-INIT-001",
        "id_obat": "OBT-001",
        "waktu": "2026-09-01T08:00:00Z",
        "jenis_mutasi": "SALDO_AWAL",
        "jumlah": 100,
        "stok_awal": 0,
        "stok_akhir": 100,
        "referensi": "INVENTORI-OPNAME-SEPT-2026",
        "keterangan": "Saldo awal inventori bulan berjalan"
    },
    {
        "id_mutasi": "MUT-INIT-002",
        "id_obat": "OBT-002",
        "waktu": "2026-09-01T08:00:00Z",
        "jenis_mutasi": "SALDO_AWAL",
        "jumlah": 50,
        "stok_awal": 0,
        "stok_akhir": 50,
        "referensi": "INVENTORI-OPNAME-SEPT-2026",
        "keterangan": "Saldo awal inventori bulan berjalan"
    },
    {
        "id_mutasi": "MUT-INIT-003",
        "id_obat": "OBT-003",
        "waktu": "2026-09-01T08:00:00Z",
        "jenis_mutasi": "SALDO_AWAL",
        "jumlah": 30,
        "stok_awal": 0,
        "stok_akhir": 30,
        "referensi": "INVENTORI-OPNAME-SEPT-2026",
        "keterangan": "Saldo awal inventori bulan berjalan"
    },
    {
        "id_mutasi": "MUT-INIT-004",
        "id_obat": "OBT-004",
        "waktu": "2026-09-01T08:00:00Z",
        "jenis_mutasi": "SALDO_AWAL",
        "jumlah": 5,
        "stok_awal": 0,
        "stok_akhir": 5,
        "referensi": "INVENTORI-OPNAME-SEPT-2026",
        "keterangan": "Saldo awal stok menipis"
    },
    {
        "id_mutasi": "MUT-INIT-005",
        "id_obat": "OBT-005",
        "waktu": "2026-09-01T08:00:00Z",
        "jenis_mutasi": "SALDO_AWAL",
        "jumlah": 10,
        "stok_awal": 0,
        "stok_akhir": 10,
        "referensi": "INVENTORI-OPNAME-SEPT-2026",
        "keterangan": "Saldo stok untuk uji race condition"
    }
]

# Data E-Resep Masuk Awal
INITIAL_RESEP = [
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
        "status": "menunggu",  # menunggu | ditelaah | siap_dispense | selesai | ditolak
        "telaah_apoteker": None,
        "dispense_info": None,
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
    },
    {
        "id_resep": "RSP-20260912-002",
        "no_resep": "E-RSP/2026/09/002",
        "waktu_kirim": "2026-09-12T09:05:22Z",
        "id_kunjungan": "VISIT-2026-091202",
        "no_rm": "RM-2026-00892",
        "nama_pasien": "Dewi Sartika",
        "usia_pasien": "28 tahun",
        "berat_badan_kg": 54.0,
        "riwayat_alergi": ["Amoxicillin"],
        "ruang_periksa": "Poli Gigi & Mulut",
        "dokter_penulis": "drg. Hendra Kusuma",
        "status": "menunggu",
        "telaah_apoteker": None,
        "dispense_info": None,
        "items": [
            {
                "id_obat": "OBT-001",
                "nama_obat": "Paracetamol 500 mg Tablet",
                "jumlah": 10,
                "satuan": "Tablet",
                "signa": "3 x 1 tablet sesudah makan",
                "catatan_khusus": "Pereda nyeri pasca pencabutan gigi"
            }
        ]
    },
    {
        "id_resep": "RSP-20260912-003",
        "no_resep": "E-RSP/2026/09/003",
        "waktu_kirim": "2026-09-12T09:15:00Z",
        "id_kunjungan": "VISIT-2026-091203",
        "no_rm": "RM-2026-00333",
        "nama_pasien": "Ahmad Dani",
        "usia_pasien": "12 tahun",
        "berat_badan_kg": 34.0,
        "riwayat_alergi": [],
        "ruang_periksa": "Poli Anak (MTBS)",
        "dokter_penulis": "dr. Maya Indriani",
        "status": "menunggu",
        "telaah_apoteker": None,
        "dispense_info": None,
        "items": [
            {
                "id_obat": "OBT-004",
                "nama_obat": "Oralit Serbuk Sachet",
                "jumlah": 20,  # Meminta 20 sachet, padahal stok hanya 5 (Negative Stock Test Case)
                "satuan": "Sachet",
                "signa": "Setiap kali BAB cair larutkan 1 sachet dalam 200ml air matang",
                "catatan_khusus": "Pasien diare dehidrasi ringan"
            }
        ]
    }
]

# Database State
STATE = {
    "obat": [dict(o) for o in INITIAL_OBAT],
    "mutasi": [dict(m) for m in INITIAL_MUTASI],
    "resep": [dict(r) for r in INITIAL_RESEP]
}

def get_utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

class FarmasiRequestHandler(BaseHTTPRequestHandler):
    def _send_response_json(self, status_code, data):
        payload = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        raw_path = parsed.path
        # Normalisasi path: dukung baik /api/v1/farmasi/... maupun langsung /...
        path = raw_path
        if path.startswith("/api/v1/farmasi"):
            path = path[len("/api/v1/farmasi"):]
            if not path:
                path = "/"
        query = parse_qs(parsed.query)

        # Health check
        if path == "/health" or raw_path == "/health":
            return self._send_response_json(200, {
                "status": "UP",
                "service": "SIMPUS Farmasi & E-Resep API",
                "version": "1.0.0",
                "timestamp": get_utc_now(),
                "author": "Muhammad Rafli Aolia"
            })

        # GET /obat -> Daftar stok obat inventori
        if path == "/obat":
            with DB_LOCK:
                obat_list = [dict(o) for o in STATE["obat"]]
            return self._send_response_json(200, {
                "status": "success",
                "total_items": len(obat_list),
                "data": obat_list
            })

        # GET /obat/{id}/kartu-stok -> Log mutasi stok obat
        match_kartu = re.match(r"^/obat/([^/]+)/kartu-stok$", path)
        if match_kartu:
            id_obat = match_kartu.group(1)
            with DB_LOCK:
                obat = next((o for o in STATE["obat"] if o["id_obat"] == id_obat), None)
                if not obat:
                    return self._send_response_json(404, {
                        "status": "error",
                        "message": f"Obat dengan ID '{id_obat}' tidak ditemukan."
                    })
                mutasi_obat = [m for m in STATE["mutasi"] if m["id_obat"] == id_obat]
            return self._send_response_json(200, {
                "status": "success",
                "id_obat": id_obat,
                "nama_obat": obat["nama_obat"],
                "stok_saat_ini": obat["stok"],
                "total_mutasi": len(mutasi_obat),
                "data": mutasi_obat
            })

        # GET /resep?status=menunggu -> Daftar e-resep masuk
        if path == "/resep":
            status_filter = query.get("status", [None])[0]
            with DB_LOCK:
                if status_filter:
                    filtered = [r for r in STATE["resep"] if r["status"].lower() == status_filter.lower()]
                else:
                    filtered = list(STATE["resep"])
            return self._send_response_json(200, {
                "status": "success",
                "filter_status": status_filter,
                "total": len(filtered),
                "data": filtered
            })

        # GET /resep/{id} -> Detail spesifik resep
        match_resep = re.match(r"^/resep/([^/]+)$", path)
        if match_resep:
            id_resep = match_resep.group(1)
            with DB_LOCK:
                resep = next((r for r in STATE["resep"] if r["id_resep"] == id_resep), None)
            if not resep:
                return self._send_response_json(404, {
                    "status": "error",
                    "message": f"Resep dengan ID '{id_resep}' tidak ditemukan."
                })
            return self._send_response_json(200, {
                "status": "success",
                "data": resep
            })

        # Fallback 404
        return self._send_response_json(404, {
            "status": "error",
            "message": f"Endpoint GET {path} tidak ditemukan."
        })

    def do_POST(self):
        parsed = urlparse(self.path)
        raw_path = parsed.path
        # Normalisasi path: dukung baik /api/v1/farmasi/... maupun langsung /...
        path = raw_path
        if path.startswith("/api/v1/farmasi"):
            path = path[len("/api/v1/farmasi"):]
            if not path:
                path = "/"

        # Baca Body Request
        content_length = int(self.headers.get("Content-Length", 0))
        body_str = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
        try:
            body = json.loads(body_str) if body_str else {}
        except json.JSONDecodeError:
            return self._send_response_json(400, {
                "status": "error",
                "message": "Invalid JSON format."
            })

        # POST /resep/reset -> Reset database ke state awal (bantu pengujian berulang)
        if path == "/resep/reset":
            with DB_LOCK:
                import copy
                STATE["obat"] = copy.deepcopy(INITIAL_OBAT)
                STATE["mutasi"] = copy.deepcopy(INITIAL_MUTASI)
                STATE["resep"] = copy.deepcopy(INITIAL_RESEP)
            return self._send_response_json(200, {
                "status": "success",
                "message": "State database farmasi & inventori berhasil direset ke kondisi awal."
            })

        # POST /resep/simulasi-baru -> Buat e-resep baru (simulasi dokter dari poli)
        if path == "/resep/simulasi-baru":
            with DB_LOCK:
                new_idx = len(STATE["resep"]) + 1
                new_id = f"RSP-20260912-{new_idx:03d}"
                resep_obj = {
                    "id_resep": new_id,
                    "no_resep": body.get("no_resep", f"E-RSP/2026/09/{new_idx:03d}"),
                    "waktu_kirim": get_utc_now(),
                    "id_kunjungan": body.get("id_kunjungan", f"VISIT-2026-{new_idx:06d}"),
                    "no_rm": body.get("no_rm", "RM-2026-99999"),
                    "nama_pasien": body.get("nama_pasien", "Pasien Baru"),
                    "usia_pasien": body.get("usia_pasien", "30 tahun"),
                    "berat_badan_kg": body.get("berat_badan_kg", 60.0),
                    "riwayat_alergi": body.get("riwayat_alergi", []),
                    "ruang_periksa": body.get("ruang_periksa", "Poli Umum"),
                    "dokter_penulis": body.get("dokter_penulis", "dr. Umum Puskesmas"),
                    "status": "menunggu",
                    "telaah_apoteker": None,
                    "dispense_info": None,
                    "items": body.get("items", [])
                }
                STATE["resep"].append(resep_obj)
            return self._send_response_json(201, {
                "status": "success",
                "message": "Resep elektronik dari poli periksa berhasil diterbitkan.",
                "data": resep_obj
            })

        # POST /resep/{id}/telaah -> Telaah resep oleh apoteker
        match_telaah = re.match(r"^/resep/([^/]+)/telaah$", path)
        if match_telaah:
            id_resep = match_telaah.group(1)
            with DB_LOCK:
                resep = next((r for r in STATE["resep"] if r["id_resep"] == id_resep), None)
                if not resep:
                    return self._send_response_json(404, {
                        "status": "error",
                        "message": f"Resep dengan ID '{id_resep}' tidak ditemukan."
                    })

                if resep["status"] == "selesai":
                    return self._send_response_json(400, {
                        "status": "error",
                        "message": "Resep sudah selesai didispense, tidak dapat ditelaah ulang."
                    })

                # Validasi payload telaah
                apoteker = body.get("apoteker", "Apoteker Jaga, S.Farm., Apt.")
                keputusan = body.get("keputusan", "DISETUJUI").upper()  # DISETUJUI | DITOLAK
                telaah_admin = body.get("telaah_administratif", {})
                telaah_farmasetis = body.get("telaah_farmasetis", {})
                telaah_klinis = body.get("telaah_klinis", {})
                catatan = body.get("catatan", "Kesesuaian dosis dan ketersediaan obat telah diverifikasi.")

                # Pengecekan otomatis alergi obat jika dokter meresepkan obat alergi pasien
                alergi_terdeteksi = []
                for item in resep["items"]:
                    for alergi in resep.get("riwayat_alergi", []):
                        if alergi.lower() in item["nama_obat"].lower():
                            alergi_terdeteksi.append({
                                "id_obat": item["id_obat"],
                                "nama_obat": item["nama_obat"],
                                "alergen": alergi
                            })

                if alergi_terdeteksi and keputusan == "DISETUJUI" and not body.get("override_alergi", False):
                    return self._send_response_json(422, {
                        "status": "error",
                        "error_type": "KONTRAINDIKASI_ALERGI",
                        "message": "Peringatan Alergi Obat: Pasien memiliki riwayat alergi terhadap obat yang diresepkan!",
                        "detail_alergi": alergi_terdeteksi,
                        "rekomendasi": "Lakukan konfirmasi kembali ke dokter penulis resep atau tolak resep secara klinis."
                    })

                telaah_data = {
                    "waktu_telaah": get_utc_now(),
                    "apoteker": apoteker,
                    "keputusan": keputusan,
                    "telaah_administratif": {
                        "keabsahan_resep": telaah_admin.get("keabsahan_resep", True),
                        "kejelasan_tulisan_signa": telaah_admin.get("kejelasan_tulisan_signa", True),
                        "identitas_pasien_sesuai": telaah_admin.get("identitas_pasien_sesuai", True)
                    },
                    "telaah_farmasetis": {
                        "bentuk_sediaan_tepat": telaah_farmasetis.get("bentuk_sediaan_tepat", True),
                        "dosis_dan_aturan_pakai_tepat": telaah_farmasetis.get("dosis_dan_aturan_pakai_tepat", True),
                        "stabilitas_obat_terjamin": telaah_farmasetis.get("stabilitas_obat_terjamin", True)
                    },
                    "telaah_klinis": {
                        "ketepatan_indikasi": telaah_klinis.get("ketepatan_indikasi", True),
                        "tidak_ada_duplikasi": telaah_klinis.get("tidak_ada_duplikasi", True),
                        "bebas_interaksi_obat_fatal": telaah_klinis.get("bebas_interaksi_obat_fatal", True),
                        "bebas_kontraindikasi_alergi": len(alergi_terdeteksi) == 0
                    },
                    "catatan": catatan
                }

                resep["telaah_apoteker"] = telaah_data
                if keputusan == "DISETUJUI":
                    resep["status"] = "siap_dispense"
                else:
                    resep["status"] = "ditolak"

            return self._send_response_json(200, {
                "status": "success",
                "message": f"Resep {id_resep} berhasil ditelaah dengan keputusan: {keputusan}.",
                "status_resep": resep["status"],
                "data": resep
            })

        # POST /resep/{id}/dispense -> Dispensing & Pemotongan Stok Inventori Atomik
        match_dispense = re.match(r"^/resep/([^/]+)/dispense$", path)
        if match_dispense:
            id_resep = match_dispense.group(1)
            petugas_dispense = body.get("petugas_dispense", "Asisten Apoteker / Petugas Farmasi")

            # ATOMIC TRANSACTION DENGAN THREAD LOCK (PROTEKSI RACE CONDITION)
            with DB_LOCK:
                resep = next((r for r in STATE["resep"] if r["id_resep"] == id_resep), None)
                if not resep:
                    return self._send_response_json(404, {
                        "status": "error",
                        "message": f"Resep dengan ID '{id_resep}' tidak ditemukan."
                    })

                # Cek apakah sudah pernah didispense (mencegah double dispense pada race condition)
                if resep["status"] == "selesai":
                    return self._send_response_json(409, {
                        "status": "error",
                        "error_type": "ALREADY_DISPENSED",
                        "message": f"Resep {id_resep} sudah berstatus 'selesai' didispense sebelumnya. Double dispensing dicegah!",
                        "dispense_info": resep.get("dispense_info")
                    })

                # PHASE 1: VALIDASI KECUKUPAN STOK (NEGATIVE STOCK CHECK DULUAN)
                insufficient_stock_errors = []
                stok_snapshot_before = {}

                for item in resep["items"]:
                    id_obat = item["id_obat"]
                    qty_diminta = int(item["jumlah"])
                    obat_inv = next((o for o in STATE["obat"] if o["id_obat"] == id_obat), None)

                    if not obat_inv:
                        insufficient_stock_errors.append({
                            "id_obat": id_obat,
                            "nama_obat": item["nama_obat"],
                            "alasan": "Obat tidak terdaftar dalam katalog inventori farmasi."
                        })
                        continue

                    stok_snapshot_before[id_obat] = obat_inv["stok"]

                    if obat_inv["stok"] < qty_diminta:
                        insufficient_stock_errors.append({
                            "id_obat": id_obat,
                            "nama_obat": obat_inv["nama_obat"],
                            "stok_tersedia": obat_inv["stok"],
                            "stok_diminta": qty_diminta,
                            "defisit": qty_diminta - obat_inv["stok"],
                            "alasan": "Kuantitas stok tidak mencukupi (Negative Stock Protection terpicu)."
                        })

                # Jika ada item yang stoknya kurang, batalkan seluruh transaksi secara atomik (Rollback)
                if insufficient_stock_errors:
                    return self._send_response_json(422, {
                        "status": "error",
                        "error_type": "NEGATIVE_STOCK_PROTECTION",
                        "message": "Dispensing dibatalkan! Stok obat tidak mencukupi, sistem mencegah mutasi stok negatif.",
                        "detail_defisit": insufficient_stock_errors
                    })

                # Resep wajib lolos telaah terlebih dahulu
                if resep["status"] != "siap_dispense":
                    return self._send_response_json(422, {
                        "status": "error",
                        "error_type": "UNVERIFIED_PRESCRIPTION",
                        "message": f"Resep {id_resep} belum dapat didispense karena status saat ini '{resep['status']}'. Resep wajib berstatus 'siap_dispense' (lolos telaah apoteker)."
                    })

                # PHASE 2: EKSEKUSI PEMOTONGAN STOK & PENCATATAN KARTU STOK
                waktu_eksekusi = get_utc_now()
                rincian_mutasi = []
                stok_snapshot_after = {}

                for item in resep["items"]:
                    id_obat = item["id_obat"]
                    qty_diminta = int(item["jumlah"])
                    obat_inv = next(o for o in STATE["obat"] if o["id_obat"] == id_obat)

                    stok_awal = obat_inv["stok"]
                    stok_akhir = stok_awal - qty_diminta
                    obat_inv["stok"] = stok_akhir
                    stok_snapshot_after[id_obat] = stok_akhir

                    # Catat kartu stok log mutasi
                    id_mutasi = f"MUT-{datetime.now().strftime('%Y%m%d%H%M%S')}-{id_obat[-3:]}"
                    mutasi_entry = {
                        "id_mutasi": id_mutasi,
                        "id_obat": id_obat,
                        "nama_obat": obat_inv["nama_obat"],
                        "waktu": waktu_eksekusi,
                        "jenis_mutasi": "KELUAR_DISPENSING",
                        "jumlah": qty_diminta,
                        "stok_awal": stok_awal,
                        "stok_akhir": stok_akhir,
                        "referensi": resep["no_resep"],
                        "id_resep": id_resep,
                        "petugas": petugas_dispense,
                        "keterangan": f"Pengeluaran obat pasien {resep['nama_pasien']} (No RM: {resep['no_rm']})"
                    }
                    STATE["mutasi"].append(mutasi_entry)
                    rincian_mutasi.append(mutasi_entry)

                # Finalisasi status resep
                resep["status"] = "selesai"
                resep["dispense_info"] = {
                    "waktu_dispense": waktu_eksekusi,
                    "petugas_dispense": petugas_dispense,
                    "total_item_obat": len(resep["items"]),
                    "rincian_pemotongan": [
                        {
                            "id_obat": m["id_obat"],
                            "nama_obat": m["nama_obat"],
                            "jumlah_keluar": m["jumlah"],
                            "stok_sebelum": m["stok_awal"],
                            "stok_sesudah": m["stok_akhir"]
                        }
                        for m in rincian_mutasi
                    ]
                }

            # Response berhasil
            return self._send_response_json(200, {
                "status": "success",
                "message": f"Resep {id_resep} berhasil didispense. Stok inventori terpotong otomatis secara real-time.",
                "status_resep": "selesai",
                "kondisi_stok": {
                    "sebelum_dispense": stok_snapshot_before,
                    "sesudah_dispense": stok_snapshot_after
                },
                "dispense_summary": resep["dispense_info"]
            })

        # Fallback 404
        return self._send_response_json(404, {
            "status": "error",
            "message": f"Endpoint POST {path} tidak ditemukan."
        })

def run_server(port=8080):
    server_address = ("127.0.0.1", port)
    httpd = ThreadingHTTPServer(server_address, FarmasiRequestHandler)
    print(f"============================================================")
    print(f"[*] SIMPUS Farmasi & E-Resep API Server running on http://127.0.0.1:{port}")
    print(f"[*] Ready for automated testing & postman collection")
    print(f"============================================================")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nServer shutting down...")
        httpd.server_close()

if __name__ == "__main__":
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    run_server(port)
