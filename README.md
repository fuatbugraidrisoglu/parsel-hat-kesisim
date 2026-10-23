# Parsel–Hat Kesişim Hesabı  —  by Fuat Buğra

Tek bir DXF içindeki parsel, ada/parsel yazıları, mahalle sınırları ve hat katmanlarından,
hattın kesiştiği parselleri ve kesişim alanlarını hesaplar. Çıktı: tek bir Excel ve
yüklenen DXF'in üstüne kesişim katmanları eklenmiş yeni bir DXF.

## Kullanım (exe ile)
1. `ParselHatKesisim.zip` dosyasını bir klasöre çıkar.
2. `ParselHatKesisim.exe` dosyasını çalıştır. (Kurulum gerekmez.)
3. **DXF Seç** ile dosyayı aç. Katmanlar listelenir.
4. Parsel çokgenleri, ada/parsel yazıları, hat, mahalle sınırı ve mahalle adı katmanlarını seç.
5. **Hesapla**. Çıktılar DXF'in klasörüne (ya da seçtiğin klasöre) yazılır:
   - `kesisen_parseller.xlsx` (mahalle başına sayfa, `tum_liste`, `parsel_toplam`, `kose_koordinatlari`)
   - `<dxf adı>_kesisim.dxf`

Windows ilk açılışta "Windows bilgisayarınızı korudu" uyarısı verebilir (imzasız uygulama).
**Daha fazla bilgi → Yine de çalıştır** de.

## Exe'yi GitHub'da üretme (kendi bilgisayarına Python kurmadan)
1. github.com'da yeni bir depo (repository) oluştur.
2. Bu klasördeki tüm dosyaları depoya yükle (`.github/workflows/build.yml` dahil; klasör yapısı korunmalı).
3. Depoda **Actions** sekmesine gir → **Windows EXE derle** → **Run workflow**.
4. İş bitince (birkaç dakika) çalıştırmanın sayfasında **Artifacts** altından `ParselHatKesisim` zip'ini indir.
5. Kalıcı bir indirme bağlantısı istersen depoda `v1.0` gibi bir etiket (tag) oluştur; zip,
   **Releases** bölümüne otomatik eklenir.

## Kendi bilgisayarında denemek / derlemek (isteğe bağlı)
```
pip install -r requirements.txt
python app.py
pip install pyinstaller
pyinstaller --noconfirm --windowed --name ParselHatKesisim --collect-all ezdxf --collect-all shapely app.py
```
Exe, `dist/ParselHatKesisim/` klasöründe oluşur.

## Notlar
- Koordinatlar metre cinsinden düzlem koordinatı olmalı (ITRF96 TM gibi). Derece cinsindeyse uyarı verir.
- DXF'te x = Doğu (Y), y = Kuzey (X) kabul edilir.
- Mahalle bilgisi idari mahalle sınırından gelir; tapu mahallesiyle sınırda farklı olabilir.
- Köşe noktaları saat yönünde, en kuzey (eşitse en batı) köşeden numaralanır.
