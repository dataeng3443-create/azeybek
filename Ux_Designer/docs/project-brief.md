# Proje kapsamı

> Güncel karar: Yerel web arayüzü, PBIT giriş/çıkış ve Ollama üzerinden Llama. Çalışan ilk sürüm ve sınırları için README.md esas alınır. Aşağıdaki belge ilk kapsam taslağıdır.

## Amaç

Analistin oluşturduğu mevcut bir Power BI raporunu daha okunabilir, tutarlı ve profesyonel hale getirmek. Kaynak prompt, ürünün tasarım gereksinimlerini tanımlar; tek başına dosya işleme yöntemi veya çalışan bir uygulama değildir.

## Hedef kullanıcı

Çalışan bir raporu olan ve görsel tasarım desteği isteyen BI analisti. Raporun hedef kitlesi tasarım sırasında ayrıca belirlenir; varsayılan yön yönetici odaklı, açık renkli kurumsal tasarımdır.

## Önerilen ilk sürüm akışı

1. Mevcut rapor yapısını al ve desteklenen girdiyi doğrula.
2. Sayfaları, görselleri, veri bağlantılarını, filtreleri ve yerleşimi envantere çıkar.
3. Kanıta dayalı tasarım sorunlarını belirle.
4. Ortak renk, tipografi, boşluk ve yüzey kurallarını oluştur.
5. Görsel değişiklikleri ayrı bir çıktı kopyasına uygula; kaynak raporu koru.
6. Korunması gereken alanları kaynakla karşılaştır.
7. Power BI ortamında görünüm ve etkileşimleri kontrol et.
8. Değişiklik özetini, doğrulama sonuçlarını ve gözlemlenebilen tasarım değerlendirmesini sun.

Bu akış bir ürün önerisidir; desteklenecek dosya biçimi ve otomasyon seviyesi henüz kararlaştırılmamıştır.

## Değişiklik sınırları

İzin verilen tasarım alanları: konum, boyut, hizalama, boşluk, tipografi, arka plan, kenarlık ve analitik anlamı değiştirmeyen görsel biçimlendirme.

Korunacak alanlar: veri kaynakları, model, tablolar, kolonlar, ölçüler, DAX, Power Query, ilişkiler, güvenlik/RLS, yenileme ayarları, filtre mantığı, görsel veri bağları ve analitik anlam.

İlk sürümde grafik türü değiştirmeyi kapsam dışında tutmak önerilir. Sonraki sürümlerde ancak bilgi, etkileşim ve anlam eşdeğerliği doğrulandığında ele alınır.

Mevcut anlam taşıyan renkler, koşullu biçimlendirme, sıralama, tooltip, drillthrough, bookmark ve görseller arası etkileşimler de korunmalıdır. Tasarım değişikliği bu davranışları etkiliyorsa otomatik uygulama yerine inceleme gerektirir.

## Varsayılan tasarım yönü

- Açık nötr sayfa arka planı ve sade analitik yüzeyler.
- Koyu ana metin, okunabilir ikincil metin ve kontrollü bir vurgu rengi.
- Sayfa başlığı, KPI, ana eğilim ve destekleyici analiz sıralaması.
- Tuval boyutuna uyarlanan 8/16/24/32 boşluk ritmi.
- Tutarlı tipografi ve sayfalar arası ortak tasarım dili.
- Anlam taşıyan renkleri koruma; durumu yalnızca renk ile ifade etmeme.

## İlk sürüm kabul ölçütleri

- Kaynak rapor değişmeden kalır ve çıktı ayrı tutulur.
- Önemli analitik bileşenler ve veri bağları korunur.
- Korunan alanlardaki beklenmeyen değişiklikler teslimi durdurur.
- Desteklenmeyen bileşenler sessizce dönüştürülmez; açıkça raporlanır.
- Çıktı hedef Power BI ortamında açılarak görsel ve işlevsel olarak doğrulanır.
- Görünümü incelenmemiş rapora önce/sonra UX puanı verilmez.
- Tasarım puanları öznel değerlendirme olarak, gözlem ve gerekçeleriyle sunulur; başarı kanıtı yerine kullanılmaz.
- Yapısal karşılaştırma, hesaplama sonuçlarının ve etkileşimlerin çalıştığına dair tek başına yeterli kanıt sayılmaz.

## Henüz kararlaştırılmayanlar

- Kullanım biçimi: yerel araç, web uygulaması veya önce örnek rapor üzerinden pilot.
- İlk örnek raporun dosya biçimi ve tasarım önizlemesinin nasıl alınacağı.
- Hedef Power BI sürümü ve doğrulama ortamı.
- Marka tercihleri ve hedef kullanıcı profili.
- AI sağlayıcısı, veri işleme sınırları ve maliyet tercihi.

## Sonraki somut adım

Kullanım biçimini seçip bir örnek rapor üzerinden girdiyi incelemek. Ardından dar kapsamlı, doğrulanabilir bir ilk sürüm kurmak: envanter → tasarım önerisi → ayrı çıktı → koruma kontrolleri → Power BI doğrulaması.
