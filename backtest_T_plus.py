# -*- coding: utf-8 -*-
"""
BACKTEST PHƯƠNG PHÁP T+ (trường hợp 7:3 và 3:7)
Chạy lại quy tắc của chỉ báo Pine "T+ Checklist" qua toàn bộ lịch sử giá ngày của từng mã
trong danh_sach_ma.txt, rồi in kết quả từng mã, tổng kết và bảng so sánh 7:3 với 3:7.

Quy tắc giao dịch:
  - Mua: giá đóng cửa (ATC) của phiên có tín hiệu "Mua". Mỗi mã giữ tối đa 1 vị thế.
  - Chỉ bán được từ phiên T+2. Từ phiên đó, nếu thỏa một trong các điều kiện sau
    thì bán ở giá đóng cửa (ATC) của chính phiên đó:
      + Chốt lời: giá đóng cửa >= giá mua + 8%
      + Cắt lỗ:   giá đóng cửa <= giá mua - 6%
      + Cắt lỗ:   giá đóng cửa gãy MA10 ngày và đồng thời thấp hơn giá mua
  - Mỗi mã có 100 triệu, mỗi lệnh dùng toàn bộ vốn của mã đó (có lãi kép).
"""
import sys
import time

import numpy as np
import pandas as pd

# =====================  CÀI ĐẶT (có thể chỉnh)  =====================
FILE_DANH_SACH = "danh_sach_ma.txt"   # file chứa danh sách mã
VON_BAN_DAU = 100_000_000             # vốn ban đầu cho MỖI mã (đồng)
CHOT_LOI = 8.0                        # chốt lời khi đóng cửa >= giá mua + bấy nhiêu %
CAT_LO_TOI_DA = 6.0                   # cắt lỗ khi đóng cửa <= giá mua - bấy nhiêu %
BAN_SOM_NHAT = 2                      # mua phiên T thì bán được từ phiên T+2
PHI_MUA = 0.15                        # phí mua (%)
PHI_BAN = 0.15                        # phí bán (%)
THUE_BAN = 0.10                       # thuế bán (%)
SO_NAM_BACKTEST = 5                   # chỉ giao dịch trong bấy nhiêu năm gần nhất (lấy thêm 1 năm trước đó để tính các đường MA)
GIAY_NGHI = 1                         # nghỉ giữa các mã (giây) để nguồn dữ liệu không chặn

# --- Chung cho cả 7:3 và 3:7 (giống chỉ báo Pine) ---
SO_PHIEN_DO_DOC = 8                   # đo độ dốc MA10 qua bấy nhiêu phiên
DOC_TOI_THIEU = 1.0                   # MA10 tăng/giảm ít nhất bấy nhiêu % trong khoảng đó

# --- Trường hợp 7:3 (MA10 dốc lên) ---
PCT_DUOI_MA10_THANG = 6.0             # giá được thấp hơn MA10 tháng tối đa (%)
MAX_PHIEN = 9                         # gãy MA10 rồi vượt lại trong DƯỚI bấy nhiêu phiên
YEU_CAU_GAY_SAU = True                # phiên gãy phải có thân nến nằm dưới MA10
THAN_NEN_DUOI_MIN = 80.0              # thân nến phiên gãy dưới MA10 tối thiểu (%)

# --- Trường hợp 3:7 (MA10 dốc xuống) ---
GAY_MANH_PCT = 6.0                    # gãy mạnh: đóng cửa thấp hơn MA10 tối thiểu (%)
GAY_GAN_DAY = 5                       # gãy mạnh phải nằm trong bấy nhiêu phiên trước lần vượt đầu
GAY_TIEP_TRONG = 5                    # vượt lên rồi gãy tiếp trong dưới bấy nhiêu phiên
HAN_VUOT_LAI_2 = 10                   # hạn vượt lại lần 2 (phiên, tính từ lần vượt đầu)
DI_NGANG_MIN = 7                      # đi ngang tối thiểu (phiên)
DI_NGANG_MAX = 10                     # đi ngang tối đa (phiên)
DI_NGANG_BIEN_DO = 4.0                # biên độ giá đóng cửa khi đi ngang tối đa (%)
TANG_MANH_PCT = 4.0                   # phiên tăng mạnh tối thiểu (%)
# =====================================================================


def doc_danh_sach(duong_dan):
    """Đọc danh sách mã. Chấp nhận mỗi dòng 1 mã, hoặc file xuất từ TradingView."""
    with open(duong_dan, encoding="utf-8-sig") as f:
        noi_dung = f.read()
    ds = []
    for dong in noi_dung.replace(",", "\n").splitlines():
        ma = dong.strip()
        if not ma or ma.startswith("#"):
            continue
        if ":" in ma:                  # dạng HOSE:VCB -> VCB
            ma = ma.split(":")[-1]
        ma = ma.strip().upper()
        if ma and ma not in ds:
            ds.append(ma)
    return ds


def lay_du_lieu(ma):
    """Tải giá ngày lâu nhất có thể (cột: time, open, high, low, close, volume)."""
    import requests
    bat_dau = int(time.time()) - int((SO_NAM_BACKTEST + 1) * 365.25 * 86400)
    r = requests.get(
        "https://dchart-api.vndirect.com.vn/dchart/history",
        params={"resolution": "D", "symbol": ma, "from": bat_dau, "to": int(time.time())},
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=60,
    )
    r.raise_for_status()
    j = r.json()
    if j.get("s") != "ok" or not j.get("t"):
        raise ValueError("không có dữ liệu cho mã này")
    df = pd.DataFrame({
        "time": pd.to_datetime(j["t"], unit="s") + pd.Timedelta(hours=7),
        "open": j["o"], "high": j["h"], "low": j["l"],
        "close": j["c"], "volume": j["v"],
    })
    return df.sort_values("time").drop_duplicates("time").reset_index(drop=True)


# ----------------------------------------------------------------------
#  TÍN HIỆU MUA
# ----------------------------------------------------------------------
def tin_hieu_7_3(d, c, o, ma10):
    """Trả về danh sách nhãn theo từng phiên: '7:3' nếu phiên đó có tín hiệu Mua, ngược lại ''."""
    n = len(c)
    # MA10 tháng tại từng phiên = (9 giá đóng cửa tháng trước + giá hiện tại) / 10
    thang = d["time"].dt.to_period("M")
    dong_thang = d.groupby(thang)["close"].last()
    tong9 = dong_thang.shift(1).rolling(9).sum()
    ma10m = (tong9.reindex(thang).to_numpy(float) + c) / 10

    tin = [""] * n
    last_cu, last_body = None, 0.0
    for i in range(1, n):
        if np.isnan(ma10[i]) or np.isnan(ma10[i - 1]):
            continue
        if c[i] < ma10[i] and c[i - 1] >= ma10[i - 1]:           # phiên gãy MA10
            last_cu = i
            hi, lo = max(o[i], c[i]), min(o[i], c[i])
            if hi == lo:
                last_body = 1.0 if hi < ma10[i] else 0.0
            else:
                last_body = min(max((ma10[i] - lo) / (hi - lo), 0.0), 1.0)
        vuot = c[i] > ma10[i] and c[i - 1] <= ma10[i - 1]
        if not vuot or last_cu is None or i - last_cu >= MAX_PHIEN:
            continue
        if YEU_CAU_GAY_SAU and last_body * 100 < THAN_NEN_DUOI_MIN:
            continue
        if i - SO_PHIEN_DO_DOC < 0 or np.isnan(ma10[i - SO_PHIEN_DO_DOC]) or np.isnan(ma10m[i]):
            continue
        c1 = c[i] >= ma10m[i] * (1 - PCT_DUOI_MA10_THANG / 100)
        c2 = ((ma10[i] / ma10[i - SO_PHIEN_DO_DOC] - 1) * 100 >= DOC_TOI_THIEU) and ma10[i] > ma10[i - 1]
        if c1 and c2:
            tin[i] = "7:3"
    return tin


def tin_hieu_3_7(c, m):
    """Trả về danh sách nhãn theo từng phiên: 'TH2.1' / 'TH2.2' nếu có tín hiệu Mua, ngược lại ''."""
    n = len(c)
    tin = [""] * n
    st, r1, deep_idx = 0, 0, 0
    hi = lo = float("nan")
    for i in range(9 + SO_PHIEN_DO_DOC, n):
        tag = ""
        doc_xuong = (m[i] / m[i - SO_PHIEN_DO_DOC] - 1) * 100 <= -DOC_TOI_THIEU
        lech = (c[i] / m[i] - 1) * 100
        gay_manh = c[i] < m[i] and doc_xuong and lech <= -GAY_MANH_PCT
        vuot = c[i] > m[i] and c[i - 1] <= m[i - 1]

        if st <= 1:
            tuoi = i - deep_idx
            if st == 1 and vuot:
                if tuoi <= GAY_GAN_DAY:
                    st, r1, hi, lo = 2, i, c[i], c[i]
                else:
                    st = 0
            elif gay_manh:
                st = 1
                deep_idx = i
            elif st == 1 and tuoi > GAY_GAN_DAY:
                st = 0
        elif st == 2:
            k = i - r1
            if c[i] < m[i]:
                st = 3 if k < GAY_TIEP_TRONG else 0
            else:
                p_hi, p_lo = hi, lo
                p_ok = (p_hi - p_lo) / p_lo * 100 <= DI_NGANG_BIEN_DO
                boom = (DI_NGANG_MIN <= k <= DI_NGANG_MAX and p_ok and c[i] > p_hi
                        and c[i] >= c[i - 1] * (1 + TANG_MANH_PCT / 100))
                if boom:
                    tag, st = "TH2.2", 0
                else:
                    hi, lo = max(hi, c[i]), min(lo, c[i])
                    now_ok = (hi - lo) / lo * 100 <= DI_NGANG_BIEN_DO
                    if (not now_ok) or k >= DI_NGANG_MAX:
                        st = 0
        elif st == 3:
            s3 = i - r1 + 1
            if vuot:
                if s3 <= HAN_VUOT_LAI_2:
                    tag = "TH2.1"
                st = 0
            elif s3 >= HAN_VUOT_LAI_2:
                st = 0
        tin[i] = tag
    return tin


# ----------------------------------------------------------------------
#  MÔ PHỎNG GIAO DỊCH
# ----------------------------------------------------------------------
def mo_phong(c, ma10, tin):
    """Chạy giao dịch cho 1 mã với 1 bộ tín hiệu. Trả về (vốn cuối, danh sách lệnh, số lệnh đang mở)."""
    von = float(VON_BAN_DAU)
    pos = None
    lenh = []
    for i in range(len(c)):
        if pos is not None and i - pos["i"] >= BAN_SOM_NHAT:
            gia, vao = c[i], pos["gia"]
            ly_do = None
            if gia >= vao * (1 + CHOT_LOI / 100):
                ly_do = "chot_loi"
            elif gia <= vao * (1 - CAT_LO_TOI_DA / 100):
                ly_do = "cat_lo_6"
            elif not np.isnan(ma10[i]) and gia < ma10[i] and gia < vao:
                ly_do = "cat_lo_ma10"
            if ly_do:
                thu = pos["so_cp"] * gia * (1 - (PHI_BAN + THUE_BAN) / 100)
                lai = thu - pos["von"]
                lenh.append({"tag": pos["tag"], "lai": lai, "pct": lai / pos["von"] * 100,
                             "giu": i - pos["i"], "ly_do": ly_do})
                von, pos = thu, None
        if pos is None and tin[i]:
            pos = {"i": i, "gia": c[i], "tag": tin[i], "von": von,
                   "so_cp": von * (1 - PHI_MUA / 100) / c[i]}
    return von, lenh, (1 if pos is not None else 0)


def thong_ke(lenh):
    """Thống kê cho một nhóm lệnh."""
    n = len(lenh)
    thang = [x for x in lenh if x["lai"] > 0]
    thua = [x for x in lenh if x["lai"] <= 0]
    tien_thang = sum(x["lai"] for x in thang)
    tien_thua = -sum(x["lai"] for x in thua)
    return {
        "n": n, "thang": len(thang), "thua": len(thua),
        "ty_le": (len(thang) / n * 100) if n else 0.0,
        "tien_thang": tien_thang, "tien_thua": tien_thua, "rong": tien_thang - tien_thua,
        "tien_thang_tb": (tien_thang / len(thang)) if thang else 0.0,
        "tien_thua_tb": (-tien_thua / len(thua)) if thua else 0.0,
        "lai_tb": (sum(x["pct"] for x in thang) / len(thang)) if thang else 0.0,
        "lo_tb": (sum(x["pct"] for x in thua) / len(thua)) if thua else 0.0,
        "ky_vong": (sum(x["pct"] for x in lenh) / n) if n else 0.0,
        "pf": (tien_thang / tien_thua) if tien_thua > 0 else (float("inf") if tien_thang > 0 else 0.0),
        "giu_tb": (sum(x["giu"] for x in lenh) / n) if n else 0.0,
        "chot_loi": sum(1 for x in lenh if x["ly_do"] == "chot_loi"),
        "cat_lo_6": sum(1 for x in lenh if x["ly_do"] == "cat_lo_6"),
        "cat_lo_ma10": sum(1 for x in lenh if x["ly_do"] == "cat_lo_ma10"),
    }


# ----------------------------------------------------------------------
#  IN KẾT QUẢ
# ----------------------------------------------------------------------
def _vn(s):
    """Đổi số kiểu 1,234.5 thành kiểu Việt Nam 1.234,5"""
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def tr(x):
    return _vn(f"{x / 1e6:,.1f}")


def pc(x, dau=False):
    return _vn(f"{x:+.1f}%" if dau else f"{x:.1f}%")


def in_tung_ma(ten, ket_qua):
    print(f"\n===== {ten} - TỪNG MÃ (đơn vị tiền: triệu đồng) =====")
    print(f"{'Mã':<7}{'Lệnh':>6}{'Thắng':>7}{'Thua':>6}{'%Thắng':>9}{'Tiền thắng':>13}"
          f"{'Tiền thua':>12}{'Ròng':>11}{'Vốn cuối':>12}{'%Lãi':>9}")
    co_lenh = [k for k in ket_qua if k["tk"]["n"] > 0]
    khong = len(ket_qua) - len(co_lenh)
    for k in sorted(co_lenh, key=lambda x: -x["tk"]["rong"]):
        t = k["tk"]
        print(f"{k['ma']:<7}{t['n']:>6}{t['thang']:>7}{t['thua']:>6}{pc(t['ty_le']):>9}"
              f"{tr(t['tien_thang']):>13}{tr(t['tien_thua']):>12}{tr(t['rong']):>11}"
              f"{tr(k['von_cuoi']):>12}{pc((k['von_cuoi'] / VON_BAN_DAU - 1) * 100, True):>9}")
    if khong:
        print(f"({khong} mã không phát sinh lệnh nào)")


def tong_ket(ten, ket_qua):
    tat_ca = [x for k in ket_qua for x in k["lenh"]]
    t = thong_ke(tat_ca)
    von0 = VON_BAN_DAU * len(ket_qua)
    von1 = sum(k["von_cuoi"] for k in ket_qua)
    mo = sum(k["dang_mo"] for k in ket_qua)
    print(f"\n----- TỔNG KẾT {ten} -----")
    print(f"Số mã chạy: {len(ket_qua)} | Tổng số lệnh: {t['n']} | Thắng: {t['thang']} | "
          f"Thua: {t['thua']} | Tỷ lệ thắng: {pc(t['ty_le'])}")
    print(f"Tổng tiền thắng: {tr(t['tien_thang'])} tr | Tổng tiền thua: {tr(t['tien_thua'])} tr | "
          f"Ròng: {tr(t['rong'])} tr")
    print(f"TB mỗi lệnh thắng: {tr(t['tien_thang_tb'])} tr | TB mỗi lệnh thua: {tr(t['tien_thua_tb'])} tr")
    print(f"Vốn ban đầu: {tr(von0)} tr -> Vốn cuối: {tr(von1)} tr ({pc((von1 / von0 - 1) * 100, True)})")
    if mo:
        print(f"({mo} lệnh đang mở ở phiên cuối chưa được tính vào thắng/thua)")
    return tat_ca, von0, von1


def bang_tong_hop_ma(kq_a, kq_b):
    """Bảng tổng hợp theo mã: gộp cả hai phương pháp (mỗi phương pháp 100 tr/mã)."""
    print("\n" + "=" * 100)
    print("TỔNG HỢP THEO MÃ (gộp 7:3 + 3:7, vốn 100 tr x 2 phương pháp mỗi mã; đơn vị tiền: triệu đồng)")
    print("=" * 100)
    print(f"{'Mã':<7}{'Lệnh':>6}{'%Thắng':>9}{'Ròng':>11}{'%Lãi cả 2':>11}{'%Lãi 7:3':>10}"
          f"{'%Lãi 3:7':>10}{'TB lệnh thắng':>15}{'TB lệnh thua':>14}")
    hang, tat_ca, von_cuoi_all, n_ma = [], [], 0.0, 0
    for a, b in zip(kq_a, kq_b):
        lenh = a["lenh"] + b["lenh"]
        if not lenh:
            continue
        t = thong_ke(lenh)
        tat_ca += lenh
        von_cuoi_all += a["von_cuoi"] + b["von_cuoi"]
        n_ma += 1
        hang.append((t["rong"], a["ma"], t,
                     (a["von_cuoi"] + b["von_cuoi"]) / (2 * VON_BAN_DAU) * 100 - 100,
                     (a["von_cuoi"] / VON_BAN_DAU - 1) * 100, (b["von_cuoi"] / VON_BAN_DAU - 1) * 100))

    def dong(ma, t, p_chung, p_a, p_b):
        tb_thang = tr(t["tien_thang_tb"]) if t["thang"] else "—"
        tb_thua = tr(t["tien_thua_tb"]) if t["thua"] else "—"
        print(f"{ma:<7}{t['n']:>6}{pc(t['ty_le']):>9}{tr(t['rong']):>11}{pc(p_chung, True):>11}"
              f"{pc(p_a, True):>10}{pc(p_b, True):>10}{tb_thang:>15}{tb_thua:>14}")

    for rong, ma, t, p_chung, p_a, p_b in sorted(hang, key=lambda x: -x[0]):
        dong(ma, t, p_chung, p_a, p_b)
    if n_ma:
        print("-" * 100)
        t = thong_ke(tat_ca)
        von_goc = 2 * VON_BAN_DAU * n_ma
        dong("TỔNG", t, (von_cuoi_all / von_goc - 1) * 100,
             (sum(k["von_cuoi"] for k in kq_a if k["lenh"]) / (VON_BAN_DAU * sum(1 for k in kq_a if k["lenh"])) - 1) * 100
             if any(k["lenh"] for k in kq_a) else 0.0,
             (sum(k["von_cuoi"] for k in kq_b if k["lenh"]) / (VON_BAN_DAU * sum(1 for k in kq_b if k["lenh"])) - 1) * 100
             if any(k["lenh"] for k in kq_b) else 0.0)
    so_khong = len(kq_a) - n_ma
    if so_khong:
        print(f"({so_khong} mã không phát sinh lệnh nào ở cả hai phương pháp)")


def bang_so_sanh(cot):
    """cot: danh sách (tên cột, thống kê, % lãi trên vốn hoặc None)"""
    print("\n" + "=" * 78)
    print("BẢNG SO SÁNH HIỆU QUẢ 7:3 VÀ 3:7")
    print("=" * 78)
    print(f"{'':<30}" + "".join(f"{ten:>12}" for ten, _, _ in cot))

    def dong(nhan, f):
        print(f"{nhan:<30}" + "".join(f"{f(t, v):>12}" for _, t, v in cot))

    dong("Số lệnh", lambda t, v: str(t["n"]))
    dong("Thắng", lambda t, v: str(t["thang"]))
    dong("Thua", lambda t, v: str(t["thua"]))
    dong("Tỷ lệ thắng", lambda t, v: pc(t["ty_le"]))
    dong("Lãi TB mỗi lệnh thắng", lambda t, v: pc(t["lai_tb"], True))
    dong("Lỗ TB mỗi lệnh thua", lambda t, v: pc(t["lo_tb"], True))
    dong("TB tiền mỗi lệnh thắng (tr)", lambda t, v: tr(t["tien_thang_tb"]) if t["thang"] else "—")
    dong("TB tiền mỗi lệnh thua (tr)", lambda t, v: tr(t["tien_thua_tb"]) if t["thua"] else "—")
    dong("Kỳ vọng mỗi lệnh", lambda t, v: pc(t["ky_vong"], True))
    dong("Hệ số lợi nhuận (thắng/thua)", lambda t, v: "—" if t["pf"] == float("inf") else _vn(f"{t['pf']:.2f}"))
    dong("Số phiên giữ TB", lambda t, v: _vn(f"{t['giu_tb']:.1f}"))
    dong("Tổng tiền thắng (tr)", lambda t, v: tr(t["tien_thang"]))
    dong("Tổng tiền thua (tr)", lambda t, v: tr(t["tien_thua"]))
    dong("Ròng (tr)", lambda t, v: tr(t["rong"]))
    dong("% lãi trên vốn", lambda t, v: "—" if v is None else pc(v, True))
    dong("Bán vì chốt lời", lambda t, v: str(t["chot_loi"]))
    dong("Bán vì cắt lỗ -6%", lambda t, v: str(t["cat_lo_6"]))
    dong("Bán vì cắt lỗ MA10", lambda t, v: str(t["cat_lo_ma10"]))
    print("(Cột TH2.1 và TH2.2 là phần nhỏ của cột 3:7; riêng '% lãi trên vốn' chỉ tính cho 7:3 và 3:7)")


def main():
    try:
        ds = doc_danh_sach(FILE_DANH_SACH)
    except FileNotFoundError:
        print(f"Không tìm thấy file {FILE_DANH_SACH}. Hãy để nó cùng thư mục với file này.")
        sys.exit(1)

    kq_a, kq_b, loi, ngay_dau, ngay_cuoi, nam = [], [], [], [], [], []
    ly_do_loi = []
    for stt, ma in enumerate(ds, 1):
        print(f"Đang tải và chạy... {stt}/{len(ds)} {ma}      ", end="\r")
        try:
            d = lay_du_lieu(ma)
            if len(d) < 300:
                raise ValueError("quá ít dữ liệu")
            c = d["close"].astype(float).to_numpy()
            o = d["open"].astype(float).to_numpy()
            ma10 = d["close"].astype(float).rolling(10).mean().to_numpy()

            moc = (d["time"] >= d["time"].iloc[-1] - pd.Timedelta(days=int(SO_NAM_BACKTEST * 365.25))).to_numpy()
            if moc.sum() < 200:
                raise ValueError("quá ít dữ liệu trong khoảng backtest")
            loc = lambda ds: [t if ok else "" for t, ok in zip(ds, moc)]   # chỉ mua trong khoảng backtest
            von_a, lenh_a, mo_a = mo_phong(c, ma10, loc(tin_hieu_7_3(d, c, o, ma10)))
            von_b, lenh_b, mo_b = mo_phong(c, ma10, loc(tin_hieu_3_7(c, ma10)))
            kq_a.append({"ma": ma, "von_cuoi": von_a, "lenh": lenh_a, "dang_mo": mo_a, "tk": thong_ke(lenh_a)})
            kq_b.append({"ma": ma, "von_cuoi": von_b, "lenh": lenh_b, "dang_mo": mo_b, "tk": thong_ke(lenh_b)})
            t0 = d.loc[moc, "time"].iloc[0]
            ngay_dau.append(t0)
            ngay_cuoi.append(d["time"].iloc[-1])
            nam.append((d["time"].iloc[-1] - t0).days / 365.25)
        except Exception as e:  # noqa
            loi.append(ma)
            ly_do_loi.append(f"{ma}: {str(e)[:70]}")
        time.sleep(GIAY_NGHI)
    print(" " * 60, end="\r")

    if not kq_a:
        print("Không lấy được dữ liệu của mã nào. Kiểm tra kết nối mạng hoặc báo lại để mình đổi nguồn dữ liệu.")
        for x in ly_do_loi[:3]:
            print("  Lỗi mẫu ->", x)
        sys.exit(1)

    print("=" * 78)
    print(f"BACKTEST T+ | {len(kq_a)} mã | dữ liệu từ {min(ngay_dau):%d/%m/%Y} đến {max(ngay_cuoi):%d/%m/%Y} "
          f"| TB {_vn(f'{sum(nam) / len(nam):.1f}')} năm/mã")
    print(f"Vốn {tr(VON_BAN_DAU)} tr/mã (lãi kép) | chốt lời +{CHOT_LOI:g}% | cắt lỗ -{CAT_LO_TOI_DA:g}% "
          f"hoặc gãy MA10 và giá mua | bán từ T+{BAN_SOM_NHAT} ở giá ATC")
    print("=" * 78)

    in_tung_ma("7:3", kq_a)
    tat_ca_a, v0a, v1a = tong_ket("7:3", kq_a)
    in_tung_ma("3:7", kq_b)
    tat_ca_b, v0b, v1b = tong_ket("3:7", kq_b)

    bang_tong_hop_ma(kq_a, kq_b)

    bang_so_sanh([
        ("7:3", thong_ke(tat_ca_a), (v1a / v0a - 1) * 100),
        ("3:7", thong_ke(tat_ca_b), (v1b / v0b - 1) * 100),
        ("TH2.1", thong_ke([x for x in tat_ca_b if x["tag"] == "TH2.1"]), None),
        ("TH2.2", thong_ke([x for x in tat_ca_b if x["tag"] == "TH2.2"]), None),
    ])

    if loi:
        print(f"\n({len(loi)} mã không lấy được dữ liệu hoặc quá ít dữ liệu: {', '.join(loi)})")
        print("  Lỗi mẫu ->", ly_do_loi[0])
    print("\nLưu ý: backtest chỉ cho biết quá khứ; dữ liệu giá có thể chưa điều chỉnh cổ tức/chia tách, "
          "và danh sách mã chỉ gồm các mã còn tồn tại.")


if __name__ == "__main__":
    main()
