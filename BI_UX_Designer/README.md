# AI UX Designer · Power BI

Yerelde çalışan web arayüzü: **PBIT yükle → tasarım modunu seç → Llama uygulasın → güncellenmiş PBIT indir.**

## Başlatma

Mac'te `Baslat.command` dosyasını açın. Başlatıcı Ollama ve web uygulamasını çalıştırıp tarayıcıyı açar.

Alternatif: proje klasöründe `python3 launch.py` çalıştırın. Doğrudan sunucu için `python3 server.py`.

Adres: http://127.0.0.1:8765/

Gerekenler: Python 3.10+, Pillow ve Ollama'da kurulu **`qwen3:8b`** (`ollama pull qwen3:8b`). Python bağımlılığı `python3 -m pip install -r requirements.txt` ile kurulur. Başka bir yerel model için sunucuyu `UX_MODEL` ortam değişkeniyle başlatabilirsiniz. Qwen3'ün düşünme modu kapatılır; model yalnızca şemaya uygun JSON döndürür.

## Tasarım modları

| Mod | Ne değişir | Ne korunur |
|---|---|---|
| **Görselleştirmeyi iyileştir** | Grafik türü, yerleşim, renk, tipografi, arka plan, kenarlık, başlık | Her görselin kolonları, ölçüleri, toplama türü, filtreleri ve bağları |
| **Sıfırdan Tasarım Uygula** | Sayfalar baştan kurulur; Qwen veri modelinden hangi alanların, hangi toplama ve grafikle gösterileceğini serbestçe seçer | Veri modeli, ölçüler, ilişkiler, RLS, rapor düzeyi filtreler |
| **Resme Uygun Görsel Tasarım** | PNG'deki renk paleti ve kompozisyon (başlık bandı, KPI satırı, grafik ızgarası, filtre paneli) uygulanır; grafik türü kuralları iyileştir moduyla aynıdır | İyileştir moduyla aynı |

Grafik türü kuralları (her modda, model ne derse desin uygulanır):
- Tarih / yıl / tarih hiyerarşisi ekseni → çizgi grafik (eksen artan sıralanır).
- Metin kategorileri (uzun etiketler) → yatay çubuk grafik; yığılmış görseller yığılmış yatay çubuk olur.
- Pasta/halka yalnızca az parçalı bütün-parça ilişkisinde; ortalamalar için asla.
- KPI kartı, tablo, filtre türleri korunur.

Sıfırdan modunda Qwen'in planı doğrulanır: alan veri modelinde var mı, kategori ile değer aynı veya ilişkili tabloda mı, toplama mantıklı mı (ölçüye toplama uygulanmaz, metin yalnızca sayılır), çizgi yalnızca zaman ekseninde mi. Geçersiz parçalar kural tabanlı olarak onarılır. Analistin mevcut raporda kullandığı alanlar modele "önemli alanlar" ipucu olarak verilir. Yer işaretleri ve detaylandırma (drillthrough) tanımları eski sayfalara bağlı olduğu için bu modda kaldırılır.

## Model kullanılamazsa

Ollama kapalıysa, model yanıt vermezse veya geçersiz JSON üretirse işlem durmaz: aynı kurallarla çalışan deterministik tasarım motoru devreye girer ve bitiş ekranında bu belirtilir. Her sayfa için modelin kullanılıp kullanılmadığı `audit.json` içindeki `model_log` alanındadır.

## Kullanım

1. `.pbit` dosyasını bırakın veya seçin (en fazla 50 MB).
2. Bir tasarım modu seçin; referans modunda PNG dashboard görselini de yükleyin.
3. Ana düğmeye basın, işlem aşamasını takip edin.
4. **Görsel hazır** ekranında `_UX.pbit` çıktısını indirin.
5. Power BI Desktop'ta açıp son görünümü ve etkileşimleri doğrulayın; ardından yeniden şablon olarak dışa aktarın.

Dosyalar ve model istekleri bu bilgisayarda kalır. İşlem kayıtları, kaynak kopyası, çıktı ve denetim raporu `.runtime/jobs/` altında tutulur.

## Kapsam ve sınırlar

- Klasik ZIP + UTF-16/UTF-8 `Report/Layout` içeren PBIT şablonları desteklenir. PBIR ve şifreli/etiketli şablonlar desteklenmez.
- Mevcut görselleri değiştiren modlarda (iyileştir, referans) her değişiklik bir izin listesiyle karşılaştırılır; sorgu, projeksiyon, filtre veya ölçü bağında tek bir fark çıkarsa çıktı oluşturulmaz.
- Yer işareti, görsel grubu, gizli/ipucu sayfası veya görsellerin arkasında şekil bulunan sayfalarda yerleşim korunur; biçim ve grafik türü yine iyileştirilir.
- Özel (custom) görseller taşınabilir ama biçimlendirilmez. Mobil yerleşimler değiştirilmez.
- PNG yalnızca bu bilgisayarda Pillow ile okunur (Qwen görsel görmez). Renkler ve kart yuvaları piksellerden çıkarılır; referanstaki metinler, simgeler ve özel görseller kopyalanmaz. Çok serili grafiklerin seri renkleri rapor temasından gelir.
- Dışarıdan düzenleme eski `SecurityBindings` paket bütünlüğü kaydını geçersiz kılar; çıktıdan çıkarılır. Veri modeli içindeki RLS/rol tanımları değiştirilmez.
- Bu uygulama Power BI render motoru değildir. Yapısal kontroller, dosyanın her Power BI sürümünde açılacağına dair garanti değildir; önce/sonra UX puanı uydurulmaz.

## Doğrulama

`python3 -m unittest discover -s tests -v`

Testler üç modu Ollama kapalıyken uçtan uca çalıştırır; çok tablolu, ölçülü, ilişkili ve gruplu/şekilli sayfalar içeren sentetik bir PBIT (`tests/fixtures.py`) ve sentetik bir referans PNG kullanır.

## Kaynaklar

- [Projenin orijinal tasarım promptu](prompts/power-bi-ai-ux-designer.md)
- [Microsoft: Power BI şablonları](https://learn.microsoft.com/en-us/power-bi/create-reports/desktop-templates)
- [Ollama: yapılandırılmış çıktılar](https://docs.ollama.com/capabilities/structured-outputs)
- [pbi-tools: PBIT extract/compile](https://pbi.tools/cli/usage.html)
- [Packer: PBIT bütünlük kaydı ve paketleme](https://github.com/anakic/Packer)

Adaptör bağımsız olarak yazılmıştır; üçüncü taraf kaynak kodu projeye kopyalanmamıştır.
