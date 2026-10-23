"""Parsel - hat kesişim çekirdeği (arayüzden bağımsız).

Colab'daki doğrulanmış mantığın geopandas'sız karşılığıdır: konum eşleştirmeleri
shapely STRtree ile, tablolar pandas ile yapılır.
"""
import os
import re
from collections import Counter

import ezdxf
import pandas as pd
import shapely
from ezdxf import recover
from shapely import STRtree
from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

ALAN = ("Polygon", "MultiPolygon")
YAZI = ("TEXT", "MTEXT")

VARSAYILAN = {
    "hat_modu": "otomatik",     # otomatik: boşluk <= kapat_max ise kapat | alan: hep kapat | cizgi: kapatma
    "kapat_max": 50.0,          # m
    "kapat_uyari": 50.0,        # m
    "sinir_tol": 0.01,          # m, sadece parsel sınırına değenleri ele
    "min_alan": 0.01,           # m2
    "hassas": 0.0001,           # m, koordinat ızgarası (4 hane)
    "ust_uste_esik": 1.0,       # m2
    "sinir_parsel_esik": 1.0,   # m2
    "baslangic_yx": None,       # (Y Doğu, X Kuzey) ya da None = hat çiziminin ilk köşesi
    "yazi_h": 3.0,              # m
    "nokta_r": 0.5,             # m
    "dxf_nokta": True,          # köşe noktaları DXF'e eklensin
    "dxf_ekstra": False,        # hat kapalı hali, parsel dışı, güzergah sırası DXF'e eklensin
}


# ---------------------------------------------------------------- DXF okuma
def dxf_oku(yol):
    """DXF'teki çizgi/çokgen/yazı nesnelerini (katman, tür, metin, geometri) listesi olarak döndürür."""
    try:
        doc = ezdxf.readfile(yol)
    except Exception:
        doc, _ = recover.readfile(yol)
    kayit = []
    for e in doc.modelspace():
        t, k, metin, g = e.dxftype(), e.dxf.layer, None, None
        if t in ("LWPOLYLINE", "POLYLINE", "LINE"):
            if t == "LWPOLYLINE":
                p, kapali = [(x, y) for x, y in e.get_points("xy")], e.closed
            elif t == "POLYLINE":
                p, kapali = [(v[0], v[1]) for v in e.points()], e.is_closed
            else:
                p, kapali = [(e.dxf.start.x, e.dxf.start.y), (e.dxf.end.x, e.dxf.end.y)], False
            if (kapali and len(p) >= 3) or (len(p) >= 4 and p[0] == p[-1]):
                g = Polygon(p)
                if not g.is_valid:
                    g = g.buffer(0)
                if g.is_empty:
                    g = None
            elif len(p) >= 2:
                g = LineString(p)
        elif t in YAZI:
            metin = " ".join((e.dxf.text if t == "TEXT" else e.plain_text()).split())
            g = Point(e.dxf.insert.x, e.dxf.insert.y) if metin else None
        if g is not None:
            kayit.append((k, t, metin, g))
    return kayit


def katman_ozeti(kayit):
    """{katman: {'çokgen': n, 'çizgi': n, 'yazı': n}}"""
    ozet = {}
    for k, t, _m, g in kayit:
        s = ozet.setdefault(k, {"çokgen": 0, "çizgi": 0, "yazı": 0})
        if t in YAZI:
            s["yazı"] += 1
        elif g.geom_type in ALAN:
            s["çokgen"] += 1
        else:
            s["çizgi"] += 1
    return ozet


# ---------------------------------------------------------------- yardımcılar
def r4(coords):
    return [(round(x, 4), round(y, 4)) for x, y in coords]


def ciz(msp, g, k_poly, k_line=None):
    k_line = k_line or k_poly
    if hasattr(g, "geoms"):
        for a in g.geoms:
            ciz(msp, a, k_poly, k_line)
    elif g.is_empty:
        return
    elif g.geom_type == "Polygon":
        msp.add_lwpolyline(r4(list(g.exterior.coords)[:-1]), close=True, dxfattribs={"layer": k_poly})
    elif g.geom_type == "LineString":
        msp.add_lwpolyline(r4(g.coords), dxfattribs={"layer": k_line})


def noktalar(msp, g, katman):
    if hasattr(g, "geoms"):
        for a in g.geoms:
            noktalar(msp, a, katman)
    elif g.geom_type == "Point" and not g.is_empty:
        msp.add_point((round(g.x, 4), round(g.y, 4)), dxfattribs={"layer": katman})


def parcala(g, alan_mi, min_alan):
    cikti = []

    def topla(a):
        if hasattr(a, "geoms"):
            for b in a.geoms:
                topla(b)
        elif a.is_empty:
            return
        elif alan_mi and a.geom_type == "Polygon" and a.area >= min_alan:
            cikti.append(a)
        elif (not alan_mi) and a.geom_type == "LineString" and a.length > 0:
            cikti.append(a)

    topla(g)
    return cikti


def koordlar(g):
    """Çokgen köşeleri saat yönünde, en kuzey (eşitse en batı) köşeden başlar. Çizgide kendi sırası."""
    if g.geom_type == "Polygon":
        g = orient(g, sign=-1.0)
        c = list(g.exterior.coords)[:-1]
        i = max(range(len(c)), key=lambda n: (c[n][1], -c[n][0]))
        return c[i:] + c[:i]
    return list(g.coords)


def en_yakin(halka, p):
    return min(range(len(halka)), key=lambda n: (halka[n][0] - p[0]) ** 2 + (halka[n][1] - p[1]) ** 2)


def zincir_hazirla(poly, ilk):
    """Alan hattının iki uzun kenarını, başlangıç ucundan bitiş ucuna giden iki zincir olarak döndürür."""
    if poly.geom_type == "MultiPolygon":
        poly = max(poly.geoms, key=lambda a: a.area)
    halka = list(poly.exterior.coords)[:-1]
    hull = list(poly.convex_hull.exterior.coords)[:-1]
    en_uzak, pa, pb = -1, None, None
    for a in range(len(hull)):
        for b in range(a + 1, len(hull)):
            dd = (hull[a][0] - hull[b][0]) ** 2 + (hull[a][1] - hull[b][1]) ** 2
            if dd > en_uzak:
                en_uzak, pa, pb = dd, hull[a], hull[b]
    i, j = sorted((en_yakin(halka, pa), en_yakin(halka, pb)))
    z1 = halka[i:j + 1]
    z2 = (halka[j:] + halka[:i + 1])[::-1]
    di = (halka[i][0] - ilk[0]) ** 2 + (halka[i][1] - ilk[1]) ** 2
    dj = (halka[j][0] - ilk[0]) ** 2 + (halka[j][1] - ilk[1]) ** 2
    if dj < di:
        z1, z2 = z1[::-1], z2[::-1]
    return LineString(z1), LineString(z2)


def km(m):
    return f"{int(m // 1000)}+{m % 1000:06.2f}"


def adlari_bul(poligonlar, metinler, ayrac):
    """poligonlar: {indeks: geometri}, metinler: [(metin, Point)] -> {indeks: içindeki metinlerin birleşimi}"""
    if not metinler:
        return {}
    ptree = STRtree([g for _m, g in metinler])
    sonuc = {}
    for i, poly in poligonlar.items():
        if poly.is_empty:
            continue
        idx = ptree.query(poly, predicate="contains")
        if len(idx):
            sonuc[i] = ayrac.join(metinler[int(j)][0] for j in sorted(int(x) for x in idx))
    return sonuc


# ---------------------------------------------------------------- ana hesap
def hesapla(yol, kayit, k_parsel, k_parsel_ad, k_hat, k_mah, k_mah_ad, ayar=None, cikti_klasor=None, log=print):
    A = dict(VARSAYILAN)
    A.update(ayar or {})
    hat_modu, kapat_max, kapat_uyari = A["hat_modu"], A["kapat_max"], A["kapat_uyari"]
    sinir_tol, min_alan, hassas = A["sinir_tol"], A["min_alan"], A["hassas"]
    ust_esik, sinir_esik = A["ust_uste_esik"], A["sinir_parsel_esik"]
    baslangic, yazi_h, nokta_r = A["baslangic_yx"], A["yazi_h"], A["nokta_r"]

    k_parsel, k_hat, k_mah = set(k_parsel or []), set(k_hat or []), set(k_mah or [])
    if not k_parsel or not k_hat:
        raise ValueError("Parsel ve hat katmanı zorunlu.")
    k_parsel_ad = set(k_parsel_ad or []) or k_parsel
    k_mah_ad = set(k_mah_ad or []) or k_mah
    cikti_klasor = cikti_klasor or os.path.dirname(os.path.abspath(yol))
    os.makedirs(cikti_klasor, exist_ok=True)

    # 1) Mahalleler
    mp, mp_ad = [], []
    if k_mah:
        mp = [g for k, t, m, g in kayit if k in k_mah and g.geom_type in ALAN]
        if not mp:
            log("UYARI: Mahalle katmanında kapalı çokgen yok, mahalle ayrımı yapılmayacak.")
        else:
            mt = [(m, g) for k, t, m, g in kayit if k in k_mah_ad and t in YAZI]
            mad = adlari_bul(dict(enumerate(mp)), mt, " ")
            mp_ad = [mad.get(i, f"Mahalle-{i + 1}") for i in range(len(mp))]
            log(f"Mahalle sayısı: {len(mp)} -> {mp_ad}")

    # 2) Hat (gerekirse kapat; açıklığı ve başlangıç köşesini not al)
    ham = [g for k, t, m, g in kayit if k in k_hat and g.geom_type in ALAN + ("LineString",)]
    if not ham:
        raise ValueError("Hat katmanında çizgi veya alan nesnesi bulunamadı.")
    hat_g, ilk_nokta, aciklik = {}, {}, {}
    for i, g in enumerate(ham):
        if g.geom_type == "LineString":
            ilk_nokta[i] = g.coords[0]
        else:
            p0 = g if g.geom_type == "Polygon" else max(g.geoms, key=lambda a: a.area)
            ilk_nokta[i] = list(p0.exterior.coords)[0]
        if baslangic:
            ilk_nokta[i] = tuple(baslangic)
        if hat_modu == "cizgi":
            g = g.boundary if g.geom_type in ALAN else g
        elif g.geom_type == "LineString" and not g.is_closed and len(g.coords) >= 3:
            bosluk = Point(g.coords[0]).distance(Point(g.coords[-1]))
            p = Polygon(g.coords)
            if not p.is_valid:
                p = p.buffer(0)
            if (hat_modu == "alan" or bosluk <= kapat_max) and not p.is_empty:
                aciklik[i] = (LineString([g.coords[0], g.coords[-1]]), bosluk)
                uyari = " | UYARI: boşluk büyük, sonucu kontrol et" if bosluk > kapat_uyari else ""
                log(f"Açık hat {i + 1}: uçlar arası boşluk {bosluk:.2f} m -> kapatıldı, alan {p.area:.1f} m²{uyari}")
                g = p
            else:
                log(f"Açık hat {i + 1}: uçlar arası boşluk {bosluk:.2f} m -> kapatılmadı (çizgi olarak kaldı)")
        if hat_modu == "alan" and g.geom_type not in ALAN:
            continue
        hat_g[i] = g
    if not hat_g:
        raise ValueError("Hat nesnesi kalmadı (hat modunu kontrol et).")
    log(f"Hat nesnesi: {len(hat_g)} | alan: {sum(g.geom_type in ALAN for g in hat_g.values())}"
        f" | çizgi: {sum(g.geom_type not in ALAN for g in hat_g.values())}")

    # 2b) Güzergah (hat yönü)
    zincir, uclar = {}, {}
    for hi, g in hat_g.items():
        if g.geom_type in ALAN:
            z1, z2 = zincir_hazirla(g, ilk_nokta[hi])
            zincir[hi] = (z1, z2)
            uclar[hi] = (((z1.coords[0][0] + z2.coords[0][0]) / 2, (z1.coords[0][1] + z2.coords[0][1]) / 2),
                         ((z1.coords[-1][0] + z2.coords[-1][0]) / 2, (z1.coords[-1][1] + z2.coords[-1][1]) / 2))
        else:
            c = list(g.coords) if g.geom_type == "LineString" else list(g.geoms[0].coords)
            uclar[hi] = (c[0], c[-1])
        log(f"Hat {hi + 1} güzergah başlangıcı: Y={uclar[hi][0][0]:.2f}, X={uclar[hi][0][1]:.2f}"
            f" | bitişi: Y={uclar[hi][1][0]:.2f}, X={uclar[hi][1][1]:.2f}")

    def konum(hi, pt):
        if hi in zincir:
            z1, z2 = zincir[hi]
            u = (z1.project(pt, normalized=True) + z2.project(pt, normalized=True)) / 2
            return u * (z1.length + z2.length) / 2
        return hat_g[hi].project(pt)

    # 3) Parseller: hatla kesişmeyenleri ele
    tum = [g for k, t, m, g in kayit if k in k_parsel and g.geom_type in ALAN]
    acik = sum(1 for k, t, m, g in kayit if k in k_parsel and g.geom_type == "LineString")
    log(f"Parsel sayısı: {len(tum)} | kapalı olmadığı için atlanan çizgi nesnesi: {acik}")
    if not tum:
        raise ValueError("Parsel katmanında kapalı çokgen bulunamadı.")
    pb, hb = shapely.total_bounds(tum), shapely.total_bounds(list(hat_g.values()))
    log(f"Parsel sınırları: {[round(float(x), 1) for x in pb]}")
    log(f"Hat sınırları:    {[round(float(x), 1) for x in hb]}")
    if hb[0] > pb[2] or hb[2] < pb[0] or hb[1] > pb[3] or hb[3] < pb[1]:
        raise ValueError("Parsel ve hat aynı bölgede değil; koordinat sistemleri farklı olabilir.")
    if max(abs(float(x)) for x in pb) <= 180:
        log("UYARI: Koordinatlar derece gibi görünüyor, alan/uzunluk metre çıkmaz.")

    tum_tree = STRtree(tum)
    aday_id = set()
    for hg in hat_g.values():
        aday_id.update(int(i) for i in tum_tree.query(hg, predicate="intersects"))
    aday_id = sorted(aday_id)
    log(f"Toplam {len(tum)} parselden {len(tum) - len(aday_id)} tanesi hatla kesişmiyor, sisteme alınmadı. "
        f"{len(aday_id)} adayla devam.")
    if not aday_id:
        raise ValueError("Hatla kesişen parsel bulunamadı.")

    # 4) Aday parsellerde iç içe poligonları ayır (içeridekileri dıştakinden çıkar)
    alan_t = shapely.area(tum)
    rep_tree = STRtree(shapely.point_on_surface(tum))
    net, ic_say = {}, 0
    for i in aday_id:
        g = tum[i]
        cocuk = [int(j) for j in rep_tree.query(g, predicate="contains") if int(j) != i and alan_t[int(j)] < alan_t[i]]
        if cocuk:
            net[i] = g.difference(unary_union([tum[j] for j in cocuk]))
            ic_say += 1
        else:
            net[i] = g
    log(f"İçinde başka parsel bulunan aday poligon: {ic_say} (içindekiler çıkarıldı)")

    # 5) Adlar
    metin = [(m, g) for k, t, m, g in kayit if k in k_parsel_ad and t in YAZI]
    adlar = adlari_bul(net, metin, " | ")
    log(f"Aday: {len(aday_id)} | yazısı bulunan: {len(adlar)} | dosyadaki yazı: {len(metin)}")

    # 5b) Aynı geometri + aynı ad: ilkini tut, diğerlerini sil (yazısı olmayanlar "adsız" sayılır)
    gorulen, silinen = set(), []
    for i in aday_id:
        anahtar = shapely.to_wkb(shapely.normalize(shapely.set_precision(tum[i], 0.001)))
        kk = (anahtar, adlar.get(i))
        if kk in gorulen:
            silinen.append(i)
        else:
            gorulen.add(kk)
    log(f"Aynı geometri ve aynı ada sahip kopya: {len(silinen)} (ilki tutuldu)")
    for i in silinen[:30]:
        log(f"   silinen poligon no {i + 1}: {adlar.get(i, f'Adsiz-{i + 1}')}")
    silinen_set = set(silinen)
    aday_id = [i for i in aday_id if i not in silinen_set]
    parsel_ad = {i: adlar.get(i, f"Adsiz-{i + 1}") for i in aday_id}

    # 6) Üst üste binen parseller (komşu sınır paylaşımı sayılmaz)
    atree = STRtree([net[i] for i in aday_id])
    ust = []
    for pos, i in enumerate(aday_id):
        for q in atree.query(net[i], predicate="intersects"):
            j = aday_id[int(q)]
            if j > i:
                ov = net[i].intersection(net[j]).area
                if ov > ust_esik:
                    ust.append((i + 1, parsel_ad[i], j + 1, parsel_ad[j], ov))
    ust.sort(key=lambda u: -u[4])
    log(f"Üst üste binen aday parsel çifti (> {ust_esik} m²): {len(ust)}")
    for u in ust[:10]:
        log(f"   #{u[0]} {u[1]}  <->  #{u[2]} {u[3]}  : {u[4]:.1f} m²")

    # 7) Her parsele mahalle ata (en çok çakıştığı mahalle)
    mah_ad, sinir_not = {}, {}
    if mp:
        mtree = STRtree(mp)
        for i in aday_id:
            g = net[i]
            ol = sorted(((g.intersection(mp[int(m)]).area, int(m)) for m in mtree.query(g, predicate="intersects")),
                        reverse=True)
            if ol and ol[0][0] > 0:
                mah_ad[i] = mp_ad[ol[0][1]]
                if len(ol) > 1 and ol[1][0] > sinir_esik:
                    sinir_not[i] = f"Mahalle sınırında: {mp_ad[ol[1][1]]} ile de çakışıyor ({ol[1][0]:.1f} m²)"

    def mah_f(pi):
        return mah_ad.get(pi, "Mahalle bilinmiyor" if mp else "TUM LISTE")

    gruplar, mukerrer = {}, {}
    for pi in aday_id:
        a_ = parsel_ad[pi]
        if a_.startswith("Adsiz-") or " | " in a_:
            continue
        gruplar.setdefault((mah_f(pi), a_), []).append(pi)
    for (_m, _a), nolar in gruplar.items():
        if len(nolar) > 1:
            for n_ in nolar:
                mukerrer[n_] = ("Aynı mahallede aynı ada/parsel başka poligonda da var (Poligon No: "
                                + ", ".join(str(x + 1) for x in nolar) + ")")

    # 8) Kesişim parçaları (parsel içi)
    pozisyon = {i: n for n, i in enumerate(aday_id)}
    parcalar, nok = [], []
    for hi, hg in hat_g.items():
        alan_mi = hg.geom_type in ALAN
        for q in atree.query(hg, predicate="intersects"):
            pi = aday_id[int(q)]
            pg = net[pi]
            t = hg.intersection(pg.buffer(-sinir_tol))
            if t.is_empty or (alan_mi and t.area < min_alan):
                continue
            k = shapely.set_precision(hg.intersection(pg), hassas)
            pcs = parcala(k, alan_mi, min_alan)
            if not pcs:
                continue
            nok.append(shapely.set_precision((hg.boundary if alan_mi else hg).intersection(pg.boundary), hassas))
            uy_a = ""
            if hi in aciklik and aciklik[hi][1] > 0.1 and aciklik[hi][0].intersects(pg):
                uy_a = f"Açıklık ({aciklik[hi][1]:.1f} m) bu parselde - kontrol et"
            for pc in pcs:
                rp = pc.representative_point()
                parcalar.append({"hat_no": hi + 1, "pi": pi, "parsel_ad": parsel_ad[pi],
                                 "parsel_alan": round(pg.area, 2), "geom": pc,
                                 "alan": round(pc.area, 2) if alan_mi else None,
                                 "uzunluk": None if alan_mi else round(pc.length, 2),
                                 "m": konum(hi, rp), "cy": round(rp.x, 4), "cx": round(rp.y, 4), "uy_a": uy_a})

    # 9) Parsel dışı kalan hat kısmı (yol/boşluk)
    kapsam = unary_union([net[i] for i in aday_id])
    dis_a, dis_c = [], []
    for hi, hg in hat_g.items():
        dg = shapely.set_precision(hg.difference(kapsam), hassas)
        if dg.is_empty:
            continue
        if hg.geom_type in ALAN:
            if dg.area >= min_alan:
                dis_a.append(dg)
        else:
            dis_c.append(dg)
    dis_a_u, dis_c_u = unary_union(dis_a), unary_union(dis_c)
    log(f"Parsel dışı kalan hat: alan {dis_a_u.area:.2f} m² | uzunluk {dis_c_u.length:.2f} m")
    tum_mah = unary_union(mp) if mp else None

    def dis_degerler(m):
        if not mp:
            return dis_a_u.area, dis_c_u.length
        if m == "Mahalle bilinmiyor":
            return dis_a_u.difference(tum_mah).area, dis_c_u.difference(tum_mah).length
        M = unary_union([mp[i] for i, a in enumerate(mp_ad) if a == m])
        return dis_a_u.intersection(M).area, dis_c_u.intersection(M).length

    if not parcalar:
        raise ValueError("Kesişen parsel bulunamadı.")

    # 10) Güzergah sırası, adlandırma, tablolar
    df = pd.DataFrame(parcalar).sort_values(["hat_no", "m"]).reset_index(drop=True)
    df["sira"] = df.index + 1
    df["n"] = df.groupby("pi").cumcount() + 1
    df["adet"] = df.groupby("pi")["pi"].transform("size")
    df["kesisim_ad"] = [f"{a}_k" if t == 1 else f"{a}_k_{n}" for a, t, n in zip(df.parsel_ad, df.adet, df.n)]
    df["mahalle"] = df["pi"].map(mah_f)
    df["uyari"] = [" ; ".join(x for x in (a, sinir_not.get(p), mukerrer.get(p)) if x)
                   for a, p in zip(df.uy_a, df["pi"])]
    for c in ("alan", "uzunluk"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    if df.alan.notna().any():
        hat_a = sum(g.area for g in hat_g.values() if g.geom_type in ALAN)
        log(f"KONTROL -> hat alanı: {hat_a:.2f} | parsel içi: {df.alan.sum():.2f} | parsel dışı: {dis_a_u.area:.2f}"
            f" | fark: {hat_a - df.alan.sum() - dis_a_u.area:.2f}")

    liste = pd.DataFrame({
        "Sıra": df.sira, "Mahalle": df.mahalle, "Ada/Parsel": df.parsel_ad, "Poligon No": df["pi"] + 1,
        "Kesişim Adı": df.kesisim_ad, "Parsel Alanı (m²)": df.parsel_alan,
        "İrtifak/Kamulaştırma Alanı (m²)": df.alan, "İrtifak Uzunluğu (m)": df.uzunluk,
        "Güzergah (km+m)": df.m.map(km), "Güzergah (m)": df.m.round(2),
        "Y (Doğu)": df.cy, "X (Kuzey)": df.cx, "Uyarı": df.uyari}).dropna(axis=1, how="all")

    mah_listeleri = {}
    for m, g in liste.groupby("Mahalle", sort=False):
        g = g.drop(columns="Mahalle")
        a, u = dis_degerler(m)
        satir_dis = {"Ada/Parsel": "PARSEL DIŞI (yol/boşluk)"}
        if a >= min_alan:
            satir_dis["İrtifak/Kamulaştırma Alanı (m²)"] = round(a, 2)
        if u > 0:
            satir_dis["İrtifak Uzunluğu (m)"] = round(u, 2)
        if len(satir_dis) > 1:
            g = pd.concat([g, pd.DataFrame([satir_dis])], ignore_index=True)
        g = g.dropna(axis=1, how="all")
        for c in ("Sıra", "Poligon No"):
            if c in g.columns:
                g[c] = g[c].astype("Int64")
        mah_listeleri[m] = g
    if mp:
        a0, _u0 = dis_degerler("Mahalle bilinmiyor")
        if a0 >= min_alan and "Mahalle bilinmiyor" not in mah_listeleri:
            log(f"NOT: Hiçbir mahalle sınırına girmeyen parsel dışı alan: {a0:.2f} m² (liste yok)")

    tp = (df.groupby("pi").agg(Mahalle=("mahalle", "first"), parsel_ad=("parsel_ad", "first"),
                               parsel_alan=("parsel_alan", "first"), parca=("pi", "size"), m=("m", "min"),
                               alan=("alan", lambda s: s.sum(min_count=1)),
                               uzunluk=("uzunluk", lambda s: s.sum(min_count=1)))
          .reset_index().sort_values("m"))
    tp["Güzergah (km+m)"] = tp.m.map(km)
    tp["Poligon No"] = tp["pi"] + 1
    tp = (tp.rename(columns={"parsel_ad": "Ada/Parsel", "parsel_alan": "Parsel Alanı (m²)",
                             "parca": "Kesişim Parça Sayısı", "alan": "İrtifak/Kamulaştırma Alanı (m²)",
                             "uzunluk": "İrtifak Uzunluğu (m)"})
            [["Mahalle", "Ada/Parsel", "Poligon No", "Parsel Alanı (m²)", "Kesişim Parça Sayısı",
              "İrtifak/Kamulaştırma Alanı (m²)", "İrtifak Uzunluğu (m)", "Güzergah (km+m)"]]
            .dropna(axis=1, how="all"))

    kose = []
    for r in df.to_dict("records"):
        for nn, (x, y) in enumerate(koordlar(r["geom"]), start=1):
            kose.append({"Sıra": r["sira"], "Mahalle": r["mahalle"], "Ada/Parsel": r["parsel_ad"],
                         "Poligon No": r["pi"] + 1, "Kesişim Adı": r["kesisim_ad"], "Nokta No": nn,
                         "Y (Doğu)": round(x, 4), "X (Kuzey)": round(y, 4)})
    kose_df = pd.DataFrame(kose)

    log(f"{df['pi'].nunique()} parsel, {len(df)} kesişim parçası | mahalle listesi: {len(mah_listeleri)}"
        f" | uyarılı parça: {int((df.uyari != '').sum())}")
    for m, g in mah_listeleri.items():
        log(f"   {m}: {len(g)} satır")

    # 11) Tek Excel dosyası
    kullanilan = {"tum_liste", "parsel_toplam", "kose_koordinatlari"}

    def sayfa_adi(ad):
        s = re.sub(r'[\\/*?:\[\]]', "_", str(ad))[:28] or "liste"
        t, n = s, 1
        while t in kullanilan:
            n += 1
            t = f"{s[:25]}_{n}"
        kullanilan.add(t)
        return t

    def bicimle(ws):
        for h in ws[1]:
            b = str(h.value or "")
            fmt = "0.0000" if b in ("Y (Doğu)", "X (Kuzey)") else ("0.00" if "(m" in b else None)
            if fmt:
                for kol in ws.iter_cols(min_col=h.column, max_col=h.column, min_row=2):
                    for hc in kol:
                        hc.number_format = fmt

    xlsx_yol = os.path.join(cikti_klasor, "kesisen_parseller.xlsx")
    with pd.ExcelWriter(xlsx_yol, engine="openpyxl") as w:
        for m, g in mah_listeleri.items():
            s = sayfa_adi(m)
            g.to_excel(w, sheet_name=s, index=False)
            bicimle(w.sheets[s])
        liste.to_excel(w, sheet_name="tum_liste", index=False)
        bicimle(w.sheets["tum_liste"])
        tp.to_excel(w, sheet_name="parsel_toplam", index=False)
        bicimle(w.sheets["parsel_toplam"])
        kose_df.to_excel(w, sheet_name="kose_koordinatlari", index=False)
        bicimle(w.sheets["kose_koordinatlari"])

    # 12) DXF: yüklenen DXF'in üstüne kesişen parseller, kesişim alanları ve köşe noktaları
    try:
        doc = ezdxf.readfile(yol)
    except Exception:
        doc, _ = recover.readfile(yol)
    if doc.dxfversion < "AC1015":
        log("UYARI: Yüklenen DXF eski sürüm (R12); üstüne eklenemedi, yeni katmanlar boş bir DXF'e yazılıyor.")
        doc = ezdxf.new("R2010")
    msp = doc.modelspace()

    def katman(ad, renk=None):
        if ad not in doc.layers:
            if renk:
                doc.layers.add(ad, color=renk)
            else:
                doc.layers.add(ad)

    katman("KESISEN_PARSEL", 3)
    katman("KESISEN_PARSEL_AD", 3)
    katman("KESISIM_ALAN", 1)
    katman("KESISIM_HAT", 1)
    katman("KESISIM_AD", 1)

    parsel_alani = df.groupby("pi")["parsel_alan"].first()
    for pi in df["pi"].unique():
        ciz(msp, tum[pi], "KESISEN_PARSEL")
        rp = tum[pi].representative_point()
        msp.add_text(f"{parsel_ad[pi]}  {parsel_alani[pi]:.2f} m2",
                     dxfattribs={"layer": "KESISEN_PARSEL_AD", "insert": (round(rp.x, 4), round(rp.y, 4)),
                                 "height": yazi_h})
    for r in df.to_dict("records"):
        ciz(msp, r["geom"], "KESISIM_ALAN", "KESISIM_HAT")
        deger = f'{r["alan"]:.2f} m2' if pd.notna(r["alan"]) else f'{r["uzunluk"]:.2f} m'
        msp.add_text(f'{r["kesisim_ad"]}  {deger}',
                     dxfattribs={"layer": "KESISIM_AD", "insert": (r["cy"], r["cx"]), "height": yazi_h})

    if A["dxf_nokta"]:
        katman("KESISIM_NOKTA", 6)
        katman("KOSE_NOKTA", 5)
        katman("KOSE_NO", 5)
        for g in nok:
            noktalar(msp, g, "KESISIM_NOKTA")
        for r in kose_df.to_dict("records"):
            y, x = r["Y (Doğu)"], r["X (Kuzey)"]
            msp.add_point((y, x), dxfattribs={"layer": "KOSE_NOKTA"})
            msp.add_circle((y, x), radius=nokta_r, dxfattribs={"layer": "KOSE_NOKTA"})
            msp.add_text(f'{r["Kesişim Adı"]}-{r["Nokta No"]}',
                         dxfattribs={"layer": "KOSE_NO", "insert": (y, x), "height": yazi_h})

    if A["dxf_ekstra"]:
        for ad in ("HAT_KAPALI", "PARSEL_DISI", "GUZERGAH_SIRA"):
            katman(ad)
        for r in df.to_dict("records"):
            msp.add_text(f'#{r["sira"]}', dxfattribs={"layer": "GUZERGAH_SIRA",
                                                       "insert": (r["cy"], r["cx"] - yazi_h * 1.5), "height": yazi_h})
        for g in hat_g.values():
            ciz(msp, g, "HAT_KAPALI")
        for g in dis_a + dis_c:
            ciz(msp, g, "PARSEL_DISI")
        for hi, (bas, bit) in uclar.items():
            msp.add_text("BASLANGIC", dxfattribs={"layer": "GUZERGAH_SIRA",
                                                   "insert": (round(bas[0], 4), round(bas[1], 4)), "height": yazi_h * 2})
            msp.add_text("BITIS", dxfattribs={"layer": "GUZERGAH_SIRA",
                                               "insert": (round(bit[0], 4), round(bit[1], 4)), "height": yazi_h * 2})

    dxf_yol = os.path.join(cikti_klasor, re.sub(r"\.dxf$", "", os.path.basename(yol), flags=re.I) + "_kesisim.dxf")
    doc.saveas(dxf_yol)
    log(f"Excel kaydedildi: {xlsx_yol}")
    log(f"DXF kaydedildi:   {dxf_yol}")
    return {"xlsx": xlsx_yol, "dxf": dxf_yol, "klasor": cikti_klasor,
            "parsel": int(df["pi"].nunique()), "parca": int(len(df))}
