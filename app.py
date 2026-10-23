"""Parsel - Hat Kesişim Hesabı: basit masaüstü arayüzü.  by Fuat Buğra"""
import os
import queue
import subprocess
import sys
import threading
import traceback
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import kesisim

KOYU = "#1f2a37"
ACIK = "#f4f6f8"
VURGU = "#2563eb"


def sayi(metin, ad):
    try:
        return float(str(metin).strip().replace(",", "."))
    except ValueError:
        raise ValueError(f"'{ad}' alanına geçerli bir sayı yaz.")


class Uygulama(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Parsel–Hat Kesişim Hesabı")
        self.geometry("1200x780")
        self.minsize(1040, 700)
        self.configure(bg=ACIK)

        self.q = queue.Queue()
        self.kayit = None
        self.katmanlar = []
        self.dxf_yolu = ""
        self.sonuc_klasor = ""
        self.calisiyor = False

        self._stil()
        self._yan_serit()
        self._ana_alan()
        self.after(100, self._kuyruk)

    # ------------------------------------------------------------ görünüm
    def _stil(self):
        st = ttk.Style(self)
        try:
            st.theme_use("clam")
        except tk.TclError:
            pass
        st.configure("TFrame", background=ACIK)
        st.configure("TLabelframe", background=ACIK)
        st.configure("TLabelframe.Label", background=ACIK, font=("Segoe UI", 10, "bold"))
        st.configure("TLabel", background=ACIK, font=("Segoe UI", 10))
        st.configure("TCheckbutton", background=ACIK, font=("Segoe UI", 10))
        st.configure("TButton", font=("Segoe UI", 10), padding=6)
        st.configure("Vurgu.TButton", font=("Segoe UI", 11, "bold"), padding=8, foreground="white", background=VURGU)
        st.map("Vurgu.TButton", background=[("active", "#1d4ed8"), ("disabled", "#93c5fd")])

    def _yan_serit(self):
        yan = tk.Frame(self, bg=KOYU, width=210)
        yan.pack(side="left", fill="y")
        yan.pack_propagate(False)
        tk.Label(yan, text="Parsel–Hat\nKesişim", bg=KOYU, fg="white",
                 font=("Segoe UI", 20, "bold"), justify="left").pack(anchor="w", padx=20, pady=(32, 6))
        tk.Label(yan, text="Kamulaştırma / irtifak\nalan ve liste hesabı", bg=KOYU, fg="#94a3b8",
                 font=("Segoe UI", 10), justify="left").pack(anchor="w", padx=20)
        tk.Label(yan, text="by Fuat Buğra", bg=KOYU, fg="#cbd5e1",
                 font=("Segoe UI", 11, "italic")).pack(side="bottom", pady=22)

    def _ana_alan(self):
        ana = tk.Frame(self, bg=ACIK, padx=18, pady=14)
        ana.pack(side="left", fill="both", expand=True)

        # 1) DXF
        f1 = ttk.LabelFrame(ana, text="1. DXF dosyası", padding=8)
        f1.pack(fill="x")
        ttk.Button(f1, text="DXF Seç…", command=self.dxf_sec).pack(side="left")
        self.yol_etiket = ttk.Label(f1, text="Henüz dosya seçilmedi.")
        self.yol_etiket.pack(side="left", padx=12)

        # 2) Katmanlar
        f2 = ttk.LabelFrame(ana, text="2. Katmanları seç (Ctrl ile birden fazla seçilebilir)", padding=8)
        f2.pack(fill="x", pady=(10, 0))
        self.lb = {}
        basliklar = [("parsel", "Parsel çokgenleri *"), ("parsel_ad", "Ada/parsel yazıları"),
                     ("hat", "Hat *"), ("mah", "Mahalle sınırı"), ("mah_ad", "Mahalle adı yazıları")]
        for c, (anahtar, baslik) in enumerate(basliklar):
            f = ttk.LabelFrame(f2, text=baslik, padding=4)
            f.grid(row=0, column=c, sticky="nsew", padx=4)
            f2.columnconfigure(c, weight=1)
            sb = ttk.Scrollbar(f, orient="vertical")
            lb = tk.Listbox(f, selectmode="extended", exportselection=False, height=9, width=24,
                            yscrollcommand=sb.set, activestyle="none", font=("Segoe UI", 9))
            sb.config(command=lb.yview)
            lb.pack(side="left", fill="both", expand=True)
            sb.pack(side="right", fill="y")
            self.lb[anahtar] = lb
        ttk.Label(f2, text="* zorunlu.  Boş bırakılırsa: ada/parsel yazıları → parsel katmanı, "
                           "mahalle adı → mahalle sınırı katmanı.  Mahalle seçilmezse tek liste çıkar.",
                  foreground="#475569").grid(row=1, column=0, columnspan=5, sticky="w", padx=4, pady=(6, 0))

        # 3) Ayarlar
        f3 = ttk.LabelFrame(ana, text="3. Ayarlar", padding=8)
        f3.pack(fill="x", pady=(10, 0))
        self.v_mod = tk.StringVar(value="otomatik (boşluk ≤ sınırsa kapat)")
        self.v_kapat = tk.StringVar(value="50")
        self.v_min = tk.StringVar(value="0.01")
        self.v_yazi = tk.StringVar(value="3")
        self.v_nokta_r = tk.StringVar(value="0.5")
        self.v_by = tk.StringVar()
        self.v_bx = tk.StringVar()
        self.v_nokta = tk.BooleanVar(value=True)
        self.v_ekstra = tk.BooleanVar(value=False)

        ttk.Label(f3, text="Açık hat:").grid(row=0, column=0, sticky="w")
        ttk.Combobox(f3, textvariable=self.v_mod, state="readonly", width=32,
                     values=["otomatik (boşluk ≤ sınırsa kapat)", "alan (hep kapat)",
                             "cizgi (kapatma, çizgi say)"]).grid(row=0, column=1, sticky="w", padx=(4, 16))
        ttk.Label(f3, text="Kapatma sınırı (m):").grid(row=0, column=2, sticky="e")
        ttk.Entry(f3, textvariable=self.v_kapat, width=8).grid(row=0, column=3, padx=(4, 16))
        ttk.Label(f3, text="Min. alan (m²):").grid(row=0, column=4, sticky="e")
        ttk.Entry(f3, textvariable=self.v_min, width=8).grid(row=0, column=5, padx=(4, 0))

        ttk.Label(f3, text="DXF yazı yüksekliği (m):").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(f3, textvariable=self.v_yazi, width=8).grid(row=1, column=1, sticky="w", padx=4, pady=(8, 0))
        ttk.Label(f3, text="Nokta yarıçapı (m):").grid(row=1, column=2, sticky="e", pady=(8, 0))
        ttk.Entry(f3, textvariable=self.v_nokta_r, width=8).grid(row=1, column=3, padx=4, pady=(8, 0))
        ttk.Label(f3, text="Başlangıç Y / X (isteğe bağlı):").grid(row=1, column=4, sticky="e", pady=(8, 0))
        bf = ttk.Frame(f3)
        bf.grid(row=1, column=5, sticky="w", pady=(8, 0))
        ttk.Entry(bf, textvariable=self.v_by, width=11).pack(side="left", padx=(4, 2))
        ttk.Entry(bf, textvariable=self.v_bx, width=11).pack(side="left")

        ttk.Checkbutton(f3, text="Köşe noktalarını DXF'e ekle (nokta + daire + numara)",
                        variable=self.v_nokta).grid(row=2, column=0, columnspan=3, sticky="w", pady=(8, 0))
        ttk.Checkbutton(f3, text="Ek katmanlar (hat kapalı hali, parsel dışı, güzergah sırası)",
                        variable=self.v_ekstra).grid(row=2, column=3, columnspan=3, sticky="w", pady=(8, 0))

        # 4) Çıktı
        f4 = ttk.LabelFrame(ana, text="4. Çıktı klasörü (boşsa DXF'in klasörü)", padding=8)
        f4.pack(fill="x", pady=(10, 0))
        self.v_cikti = tk.StringVar()
        ttk.Entry(f4, textvariable=self.v_cikti).pack(side="left", fill="x", expand=True)
        ttk.Button(f4, text="Klasör Seç…", command=self.klasor_sec).pack(side="left", padx=(8, 0))

        # Çalıştır
        f5 = ttk.Frame(ana)
        f5.pack(fill="x", pady=(12, 0))
        self.btn_hesap = ttk.Button(f5, text="Hesapla", style="Vurgu.TButton", command=self.hesapla)
        self.btn_hesap.pack(side="left")
        self.btn_ac = ttk.Button(f5, text="Çıktı klasörünü aç", command=self.klasoru_ac, state="disabled")
        self.btn_ac.pack(side="left", padx=10)
        self.ilerleme = ttk.Progressbar(f5, mode="indeterminate", length=220)
        self.ilerleme.pack(side="left", padx=10)

        # Log
        f6 = ttk.LabelFrame(ana, text="Günlük", padding=6)
        f6.pack(fill="both", expand=True, pady=(10, 0))
        sb = ttk.Scrollbar(f6, orient="vertical")
        self.log = tk.Text(f6, height=10, wrap="word", state="disabled", font=("Consolas", 9),
                           yscrollcommand=sb.set, bg="white")
        sb.config(command=self.log.yview)
        self.log.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

    # ------------------------------------------------------------ yardımcılar
    def yaz(self, metin):
        self.log.configure(state="normal")
        self.log.insert("end", str(metin) + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _meşgul(self, durum):
        self.calisiyor = durum
        self.btn_hesap.configure(state="disabled" if durum else "normal")
        if durum:
            self.ilerleme.start(12)
        else:
            self.ilerleme.stop()

    # ------------------------------------------------------------ olaylar
    def dxf_sec(self):
        yol = filedialog.askopenfilename(title="DXF dosyası seç", filetypes=[("DXF", "*.dxf"), ("Tümü", "*.*")])
        if not yol:
            return
        self.dxf_yolu = yol
        self.yol_etiket.configure(text=yol)
        self.yaz(f"DXF okunuyor: {yol}")
        self._meşgul(True)

        def oku():
            try:
                kayit = kesisim.dxf_oku(yol)
                self.q.put(("katman", (kayit, kesisim.katman_ozeti(kayit))))
            except Exception as ex:
                self.q.put(("hata", f"DXF okunamadı: {ex}\n\n{traceback.format_exc()}"))

        threading.Thread(target=oku, daemon=True).start()

    def klasor_sec(self):
        k = filedialog.askdirectory(title="Çıktı klasörünü seç")
        if k:
            self.v_cikti.set(k)

    def klasoru_ac(self):
        if not self.sonuc_klasor:
            return
        try:
            if sys.platform.startswith("win"):
                os.startfile(self.sonuc_klasor)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", self.sonuc_klasor])
            else:
                subprocess.Popen(["xdg-open", self.sonuc_klasor])
        except Exception as ex:
            messagebox.showerror("Hata", str(ex))

    def hesapla(self):
        if self.calisiyor:
            return
        if not self.kayit:
            messagebox.showwarning("Eksik", "Önce bir DXF dosyası seç.")
            return

        def sec(anahtar):
            return [self.katmanlar[i] for i in self.lb[anahtar].curselection()]

        k_parsel, k_hat = sec("parsel"), sec("hat")
        if not k_parsel or not k_hat:
            messagebox.showwarning("Eksik", "Parsel çokgenleri ve Hat katmanını seçmelisin.")
            return
        try:
            ayar = {"hat_modu": self.v_mod.get().split()[0],
                    "kapat_max": sayi(self.v_kapat.get(), "Kapatma sınırı"),
                    "min_alan": sayi(self.v_min.get(), "Min. alan"),
                    "yazi_h": sayi(self.v_yazi.get(), "DXF yazı yüksekliği"),
                    "nokta_r": sayi(self.v_nokta_r.get(), "Nokta yarıçapı"),
                    "dxf_nokta": self.v_nokta.get(), "dxf_ekstra": self.v_ekstra.get()}
            if self.v_by.get().strip() or self.v_bx.get().strip():
                ayar["baslangic_yx"] = (sayi(self.v_by.get(), "Başlangıç Y"), sayi(self.v_bx.get(), "Başlangıç X"))
        except ValueError as ex:
            messagebox.showwarning("Ayar hatası", str(ex))
            return

        k_parsel_ad, k_mah, k_mah_ad = sec("parsel_ad"), sec("mah"), sec("mah_ad")
        cikti = self.v_cikti.get().strip() or None
        self.btn_ac.configure(state="disabled")
        self.yaz("\n--- Hesap başladı ---")
        self._meşgul(True)

        def calis():
            try:
                sonuc = kesisim.hesapla(self.dxf_yolu, self.kayit, k_parsel, k_parsel_ad, k_hat, k_mah, k_mah_ad,
                                        ayar=ayar, cikti_klasor=cikti, log=lambda s: self.q.put(("log", str(s))))
                self.q.put(("bitti", sonuc))
            except Exception as ex:
                self.q.put(("hata", f"{ex}\n\n{traceback.format_exc()}"))

        threading.Thread(target=calis, daemon=True).start()

    # ------------------------------------------------------------ kuyruk
    def _kuyruk(self):
        try:
            while True:
                tur, veri = self.q.get_nowait()
                if tur == "log":
                    self.yaz(veri)
                elif tur == "katman":
                    self.kayit, ozet = veri
                    self.katmanlar = sorted(ozet)
                    for lb in self.lb.values():
                        lb.delete(0, "end")
                        for ad in self.katmanlar:
                            s = ozet[ad]
                            lb.insert("end", f'{ad}   (ç:{s["çokgen"]} z:{s["çizgi"]} y:{s["yazı"]})')
                    self.yaz(f"{len(self.katmanlar)} katman bulundu. (ç: çokgen, z: çizgi, y: yazı)")
                    self._meşgul(False)
                elif tur == "bitti":
                    self._meşgul(False)
                    self.sonuc_klasor = veri["klasor"]
                    self.btn_ac.configure(state="normal")
                    self.yaz("--- Bitti ---")
                    messagebox.showinfo("Tamamlandı",
                                        f'{veri["parsel"]} parsel, {veri["parca"]} kesişim parçası.\n\n'
                                        f'Excel: {os.path.basename(veri["xlsx"])}\nDXF: {os.path.basename(veri["dxf"])}')
                elif tur == "hata":
                    self._meşgul(False)
                    self.yaz("HATA: " + veri)
                    messagebox.showerror("Hata", veri.split("\n\n")[0])
        except queue.Empty:
            pass
        self.after(100, self._kuyruk)


if __name__ == "__main__":
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    Uygulama().mainloop()
