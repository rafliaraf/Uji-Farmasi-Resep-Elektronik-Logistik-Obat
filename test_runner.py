"""
Automated Test Runner: Pengujian Modul Farmasi & Mutasi Stok Puskesmas
Menguji:
1. Health Check Service
2. Penerimaan Resep Masuk dari Dokter (GET /api/v1/farmasi/resep?status=menunggu)
3. Deteksi Kontraindikasi Alergi Obat pada Telaah Apoteker (422 Unprocessable Entity)
4. Telaah & Verifikasi Resep Apoteker (POST /api/v1/farmasi/resep/{id}/telaah)
5. Proteksi Dispensing Tanpa Telaah (422 Unprocessable Entity)
6. Dispensing Berhasil & Pemotongan Stok Otomatis (POST /api/v1/farmasi/resep/{id}/dispense)
7. Verifikasi Perubahan Stok Sebelum vs Sesudah & Kartu Stok Mutasi Log
8. Proteksi Negative Stock (Stok Kosong / Tidak Cukup Ditolak & Rollback)
9. Proteksi Double Dispensing (409 Conflict)
10. Proteksi Race Condition / Concurrency (Multiple Concurrent Dispensing Requests)
"""

import concurrent.futures
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request

BASE_URL = "http://127.0.0.1:8080"

class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    ENDC = '\033[0m'

def make_request(method, endpoint, data=None):
    url = f"{BASE_URL}{endpoint}"
    req = urllib.request.Request(url, method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "FarmasiTestRunner/1.0")

    payload = json.dumps(data).encode("utf-8") if data else None

    try:
        with urllib.request.urlopen(req, data=payload, timeout=5) as response:
            status = response.status
            body = response.read().decode("utf-8")
            return status, json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        try:
            return e.code, json.loads(body)
        except Exception:
            return e.code, {"raw": body}
    except Exception as e:
        return 0, {"error": str(e)}

def wait_for_server(max_retries=15):
    print("[*] Menunggu API Server Farmasi aktif...")
    for _ in range(max_retries):
        status, res = make_request("GET", "/health")
        if status == 200:
            print(f"{Colors.GREEN}[+] API Server Aktif & Siap Diuji!{Colors.ENDC}\n")
            return True
        time.sleep(0.6)
    return False

def print_test_header(no, title):
    print(f"\n{Colors.BOLD}{Colors.CYAN}[TEST {no:02d}] {title}{Colors.ENDC}")
    print("-" * 65)

def run_tests():
    passed = 0
    failed = 0
    total_tests = 10

    make_request("POST", "/resep/reset")

    # TEST 1: Health Check
    print_test_header(1, "Health Check Endpoint Modul Farmasi")
    st, res = make_request("GET", "/health")
    if st == 200 and res.get("status") == "UP":
        print(f"{Colors.GREEN}[PASS]{Colors.ENDC} Server berstatus UP (Version: {res.get('version')})")
        passed += 1
    else:
        print(f"{Colors.RED}[FAIL]{Colors.ENDC} Status code: {st}, Resp: {res}")
        failed += 1

    # TEST 2: GET /api/v1/farmasi/resep?status=menunggu
    print_test_header(2, "Penerimaan E-Resep Masuk dari Ruang Periksa (Status Menunggu)")
    st, res = make_request("GET", "/resep?status=menunggu")
    if st == 200 and res.get("status") == "success" and res.get("total", 0) >= 1:
        print(f"{Colors.GREEN}[PASS]{Colors.ENDC} Berhasil mengambil antrian resep masuk!")
        print(f"       Ditemukan {res.get('total')} resep berstatus 'menunggu'.")
        for r in res.get("data", []):
            print(f"       - Resep ID: {r['id_resep']} | No: {r['no_resep']} | Pasien: {r['nama_pasien']} ({r['ruang_periksa']}) | Total Obat: {len(r['items'])}")
        passed += 1
    else:
        print(f"{Colors.RED}[FAIL]{Colors.ENDC} Status: {st}, Resp: {res}")
        failed += 1

    # TEST 3: Deteksi Alergi Obat pada Telaah Klinis
    print_test_header(3, "Telaah Resep: Deteksi Kontraindikasi Alergi Obat Pasien")
    # Resep RSP-20260912-002 punya alergi Amoxicillin, coba kita buat telaah untuk resep fiktif yg meresepkan Amoxicillin pada pasien alergi
    # Buat resep simulasi yang berisi alergen
    st_sim, res_sim = make_request("POST", "/resep/simulasi-baru", {
        "nama_pasien": "Siti Nurhaliza",
        "no_rm": "RM-2026-00999",
        "riwayat_alergi": ["Amoxicillin"],
        "ruang_periksa": "Poli Umum",
        "items": [
            {
                "id_obat": "OBT-002",
                "nama_obat": "Amoxicillin 500 mg Kapsul",
                "jumlah": 10,
                "satuan": "Kapsul",
                "signa": "3 x 1 kapsul"
            }
        ]
    })
    resep_alergi_id = res_sim["data"]["id_resep"]
    st, res = make_request("POST", f"/resep/{resep_alergi_id}/telaah", {
        "apoteker": "Apt. Nurul Hidayah, S.Farm.",
        "keputusan": "DISETUJUI",
        "catatan": "Percobaan telaah lolos"
    })
    if st == 422 and res.get("error_type") == "KONTRAINDIKASI_ALERGI":
        print(f"{Colors.GREEN}[PASS]{Colors.ENDC} Sistem berhasil mencegat resep yang mengandung obat alergi pasien!")
        print(f"       Pesan Error: {res.get('message')}")
        print(f"       Detail Alergen: {res.get('detail_alergi')}")
        passed += 1
    else:
        print(f"{Colors.RED}[FAIL]{Colors.ENDC} Harusnya 422 KONTRAINDIKASI_ALERGI tapi dapat: {st}, Resp: {res}")
        failed += 1

    # TEST 4: Telaah & Verifikasi Resep Berhasil (RSP-20260912-001)
    print_test_header(4, "Telaah Administratif, Farmasetis, & Klinis Apoteker")
    st, res = make_request("POST", "/resep/RSP-20260912-001/telaah", {
        "apoteker": "Apt. Muhammad Fauzan, S.Farm.",
        "keputusan": "DISETUJUI",
        "telaah_administratif": {
            "keabsahan_resep": True,
            "kejelasan_tulisan_signa": True,
            "identitas_pasien_sesuai": True
        },
        "telaah_farmasetis": {
            "bentuk_sediaan_tepat": True,
            "dosis_dan_aturan_pakai_tepat": True,
            "stabilitas_obat_terjamin": True
        },
        "telaah_klinis": {
            "ketepatan_indikasi": True,
            "tidak_ada_duplikasi": True,
            "bebas_interaksi_obat_fatal": True
        },
        "catatan": "Kesesuaian dosis anak/dewasa dan interaksi obat aman. Resep disetujui untuk dispensing."
    })
    if st == 200 and res.get("status_resep") == "siap_dispense":
        print(f"{Colors.GREEN}[PASS]{Colors.ENDC} Resep RSP-20260912-001 berhasil diverifikasi!")
        print(f"       Status resep berubah menjadi: '{res.get('status_resep')}'")
        passed += 1
    else:
        print(f"{Colors.RED}[FAIL]{Colors.ENDC} Status: {st}, Resp: {res}")
        failed += 1

    # TEST 5: Proteksi Dispense Resep Belum Lolos Telaah
    print_test_header(5, "Proteksi Alur: Cegah Dispensing Resep yang Belum Ditelaah")
    st, res = make_request("POST", "/resep/RSP-20260912-002/dispense", {
        "petugas_dispense": "Budi - Petugas Obat"
    })
    if st == 422 and res.get("error_type") == "UNVERIFIED_PRESCRIPTION":
        print(f"{Colors.GREEN}[PASS]{Colors.ENDC} Dispensing berhasil dicegah untuk resep yang belum berstatus 'siap_dispense'.")
        print(f"       Respons: {res.get('message')}")
        passed += 1
    else:
        print(f"{Colors.RED}[FAIL]{Colors.ENDC} Status: {st}, Resp: {res}")
        failed += 1

    # TEST 6: Cek Kondisi Stok Sebelum Dispensing (OBT-001 & OBT-002)
    print_test_header(6, "Cek Kondisi Stok Sebelum vs Sesudah Dispensing (Real-Time Mutasi)")
    st_obt1, res_obt1 = make_request("GET", "/obat/OBT-001/kartu-stok")
    st_obt2, res_obt2 = make_request("GET", "/obat/OBT-002/kartu-stok")
    stok_sebelum_1 = res_obt1["stok_saat_ini"]
    stok_sebelum_2 = res_obt2["stok_saat_ini"]
    print(f"       [KONDISI SEBELUM DISPENSE]")
    print(f"       * OBT-001 (Paracetamol 500mg) : Stok = {stok_sebelum_1} Tablet")
    print(f"       * OBT-002 (Amoxicillin 500mg) : Stok = {stok_sebelum_2} Kapsul")

    # Eksekusi Dispense Resep 001 (minta 10 pct, 15 amx)
    st_disp, res_disp = make_request("POST", "/resep/RSP-20260912-001/dispense", {
        "petugas_dispense": "Apt. Muhammad Fauzan, S.Farm."
    })

    st_obt1_after, res_obt1_after = make_request("GET", "/obat/OBT-001/kartu-stok")
    st_obt2_after, res_obt2_after = make_request("GET", "/obat/OBT-002/kartu-stok")
    stok_sesudah_1 = res_obt1_after["stok_saat_ini"]
    stok_sesudah_2 = res_obt2_after["stok_saat_ini"]

    print(f"\n       [KONDISI SESUDAH DISPENSE]")
    print(f"       * OBT-001 : {stok_sebelum_1} -> {stok_sesudah_1} (-10 Tablet)  [AKURAT]")
    print(f"       * OBT-002 : {stok_sebelum_2} -> {stok_sesudah_2} (-15 Kapsul)  [AKURAT]")

    if st_disp == 200 and stok_sesudah_1 == (stok_sebelum_1 - 10) and stok_sesudah_2 == (stok_sebelum_2 - 15):
        print(f"\n{Colors.GREEN}[PASS]{Colors.ENDC} Eksekusi dispense sukses & kuantitas stok inventori terpotong akurat!")
        passed += 1
    else:
        print(f"\n{Colors.RED}[FAIL]{Colors.ENDC} Mutasi stok tidak sesuai! Status: {st_disp}")
        failed += 1

    # TEST 7: Verifikasi Log Kartu Stok
    print_test_header(7, "Audit Trail & Kartu Stok Inventori Obat")
    mutasi_pct = res_obt1_after.get("data", [])
    last_mutasi = mutasi_pct[-1] if mutasi_pct else {}
    if (last_mutasi.get("jenis_mutasi") == "KELUAR_DISPENSING" and 
        last_mutasi.get("stok_awal") == 100 and 
        last_mutasi.get("stok_akhir") == 90 and
        last_mutasi.get("referensi") == "E-RSP/2026/09/001"):
        print(f"{Colors.GREEN}[PASS]{Colors.ENDC} Riwayat mutasi tercatat sempurna di kartu stok!")
        print(f"       ID Mutasi : {last_mutasi['id_mutasi']}")
        print(f"       Jenis     : {last_mutasi['jenis_mutasi']}")
        print(f"       Stok Awal : {last_mutasi['stok_awal']} -> Stok Akhir: {last_mutasi['stok_akhir']}")
        print(f"       Referensi : {last_mutasi['referensi']} ({last_mutasi['keterangan']})")
        passed += 1
    else:
        print(f"{Colors.RED}[FAIL]{Colors.ENDC} Log mutasi tidak valid: {last_mutasi}")
        failed += 1

    # TEST 8: Proteksi Negative Stock (Stok Kosong / Kurang)
    print_test_header(8, "Proteksi Stok Kosong / Defisit (Negative Stock Protection)")
    # RSP-20260912-003 meminta Oralit 20 sachet, stok hanya ada 5 sachet
    # Telaah dulu resepnya
    make_request("POST", "/resep/RSP-20260912-003/telaah", {
        "apoteker": "Apoteker Farmasi",
        "keputusan": "DISETUJUI"
    })
    # Coba dispense resep defisit stok
    st, res = make_request("POST", "/resep/RSP-20260912-003/dispense", {
        "petugas_dispense": "Petugas Farmasi"
    })
    # Cek stok Oralit tidak boleh berkurang sama sekali (tetap 5)
    st_oralit, res_oralit = make_request("GET", "/obat/OBT-004/kartu-stok")
    stok_oralit = res_oralit.get("stok_saat_ini")

    if st == 422 and res.get("error_type") == "NEGATIVE_STOCK_PROTECTION" and stok_oralit == 5:
        print(f"{Colors.GREEN}[PASS]{Colors.ENDC} Sistem berhasil menolak mutasi stok negatif & melakukan auto-rollback!")
        print(f"       Pesan       : {res.get('message')}")
        print(f"       Detail Defisit : {res.get('detail_defisit')}")
        print(f"       Stok Fisik Saat Ini : {stok_oralit} (Tetap utuh, tidak minus)")
        passed += 1
    else:
        print(f"{Colors.RED}[FAIL]{Colors.ENDC} Negative stock protection gagal! Status: {st}, Stok: {stok_oralit}")
        failed += 1

    # TEST 9: Proteksi Double Dispensing (Idempotency / State Protection)
    print_test_header(9, "Proteksi Double Dispensing pada Resep yang Sudah Selesai")
    st, res = make_request("POST", "/resep/RSP-20260912-001/dispense", {
        "petugas_dispense": "Petugas Lain"
    })
    if st == 409 and res.get("error_type") == "ALREADY_DISPENSED":
        print(f"{Colors.GREEN}[PASS]{Colors.ENDC} Penolakan double dispense berhasil (Status 409 Conflict)!")
        print(f"       Pesan: {res.get('message')}")
        passed += 1
    else:
        print(f"{Colors.RED}[FAIL]{Colors.ENDC} Harusnya 409 tapi didapat: {st}, Resp: {res}")
        failed += 1

    # TEST 10: Proteksi Race Condition / Concurrency (Multiple Concurrent Threads)
    print_test_header(10, "Uji Concurrency & Race Condition (Multi-Thread Concurrent Dispensing)")
    # Buat 5 e-resep serentak yang masing-masing meminta 4 tablet Salbutamol (OBT-005)
    # Total stok Salbutamol hanya 10 tablet.
    # Jika ada 5 resep @4 tablet = butuh 20 tablet.
    # Secara matematis: Resep ke-1 (4 tab) sisa 6, Resep ke-2 (4 tab) sisa 2.
    # Resep ke-3, 4, 5 WAJIB ditolak oleh sistem tanpa boleh ada negative stock (stok akhir harus tepat 2, bukan minus!).
    
    resep_race_ids = []
    for i in range(5):
        st_rc, res_rc = make_request("POST", "/resep/simulasi-baru", {
            "nama_pasien": f"Pasien Asma #{i+1}",
            "no_rm": f"RM-2026-RACE{i+1:02d}",
            "ruang_periksa": "IGD / Tindakan",
            "items": [
                {
                    "id_obat": "OBT-005",
                    "nama_obat": "Salbutamol 2 mg Tablet",
                    "jumlah": 4,
                    "satuan": "Tablet"
                }
            ]
        })
        rid = res_rc["data"]["id_resep"]
        resep_race_ids.append(rid)
        # Telaah setujui semua agar siap race di tahap dispensing
        make_request("POST", f"/resep/{rid}/telaah", {"keputusan": "DISETUJUI"})

    print(f"       Stok awal Salbutamol (OBT-005): 10 Tablet")
    print(f"       Meluncurkan 5 permintaan dispensing serentak (Multi-threading)...")

    results = []
    def concurrent_dispense(r_id):
        return make_request("POST", f"/resep/{r_id}/dispense", {"petugas_dispense": f"Thread-{r_id}"})

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(concurrent_dispense, rid) for rid in resep_race_ids]
        for f in concurrent.futures.as_completed(futures):
            results.append(f.result())

    success_count = sum(1 for status, _ in results if status == 200)
    rejected_count = sum(1 for status, _ in results if status == 422)

    st_slb, res_slb = make_request("GET", "/obat/OBT-005/kartu-stok")
    final_stock_slb = res_slb.get("stok_saat_ini")

    print(f"       Hasil Dispense Serentak:")
    print(f"       * Berhasil (200 OK)  : {success_count} resep (2 x 4 tablet = 8 tablet)")
    print(f"       * Ditolak (422 Defisit): {rejected_count} resep (Mencegah defisit)")
    print(f"       * Stok Akhir di Database: {final_stock_slb} Tablet (Sisa tepat 2 tablet)")

    if success_count == 2 and rejected_count == 3 and final_stock_slb == 2:
        print(f"\n{Colors.GREEN}[PASS]{Colors.ENDC} Race condition terproteksi sempurna! Tidak ada over-dispense & stok tidak pernah negatif!")
        passed += 1
    else:
        print(f"\n{Colors.RED}[FAIL]{Colors.ENDC} Race condition bocor! Success: {success_count}, Rejected: {rejected_count}, Stok: {final_stock_slb}")
        failed += 1

    # SUMMARY
    print("\n" + "=" * 65)
    print(f"{Colors.BOLD}RINGKASAN HASIL PENGUJIAN API MODUL FARMASI PUSKESMAS{Colors.ENDC}")
    print("=" * 65)
    print(f"Total Test Case : {total_tests}")
    print(f"Lulus (Passed)  : {Colors.GREEN}{passed}{Colors.ENDC}")
    print(f"Gagal (Failed)  : {Colors.RED}{failed}{Colors.ENDC}")
    score = (passed / total_tests) * 100
    print(f"Tingkat Keberhasilan: {Colors.BOLD}{score:.1f}%{Colors.ENDC}")
    print("=" * 65)

    return failed == 0

if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
