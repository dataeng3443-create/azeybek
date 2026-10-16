# Hızlı başlangıç

Bu proje Power BI `.pbit` dosyasındaki okunabilir semantic model metadata'sını SSAS Tabular `Model.bim` dosyasına dönüştürür.

## Bu Mac üzerinde

Proje klasöründeki **Baslat.command** dosyasına çift tıklayın. Terminal'de servis açıldıktan sonra tarayıcıdan **http://localhost:5200** adresine gidin. Durdurmak için Terminal'de Ctrl+C kullanın.

Bu bilgisayar için .NET 8 SDK, Codex çalışma klasörüne yerel olarak kurulmuştur; sistem ayarlarında PATH değişikliği yapılmamıştır. `.local-runtime` dosyası yerel SDK ve paket önbelleğinin konumunu içerir. Codex çalışma klasörünü silerseniz .NET 8 SDK'yı ayrıca kurmanız gerekir. Kaynak ZIP paketine bu bilgisayara özel dosya dahil edilmez.

5200 portunda uygulama zaten açıksa mevcut tarayıcı adresini kullanın veya önce çalışan Terminal oturumunu durdurun.

## Kullanım

1. Power BI Desktop'tan dışa aktarılan `.pbit` dosyasını seçin veya yükleme alanına bırakın.
2. Hedef SSAS sürümünü seçin; varsayılan SQL Server 2019 / 1500'dür. 1400, 1600 (SQL Server 2022) veya 1700 (SQL Server 2025) için **Custom compatibility level** seçeneğini kullanın.
3. **Generate SSAS Model** düğmesine basın.
4. Sonuçtaki uyarıları inceleyin; **Download Model.bim** ve **Download Conversion Report** ile dosyaları indirin.
5. Visual Studio'da Analysis Services Tabular Project içindeki Model.bim dosyasını değiştirin. F7 / View Code ile JSON modelini inceleyin.

`samples/SyntheticDemo.pbit` arayüzü denemek için hazırlanmış sentetik bir test paketidir; gerçek bir Power BI Desktop export'u değildir. İçindeki SQL/Excel adresleri örnektir.

## Doğrulama sınırı

Model, Microsoft'un TOM kütüphanesiyle oluşturulur ve yeniden deserialize edilerek doğrulanır. Bu kontrol, SSAS sunucusunda DAX/M çalıştırılması ve modelin deploy/process edilmesiyle aynı değildir. Hedef sunucunun credential, connector ve dosya erişim ayarları ayrıca yapılmalıdır.

Okunabilir semantic JSON bulunmayan binary/legacy PBIT yapıları için sahte model üretilmez; açık hata/uyarı döndürülür. Gerçek proje PBIT dosyanızla ve hedef SSAS/Visual Studio ortamıyla kabul testi yapılmalıdır.

Mimari, desteklenen özellikler, limitler ve standart `dotnet` komutları için [README.md](README.md) dosyasına bakın.
