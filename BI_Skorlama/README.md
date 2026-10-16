# BI Skorlama

Power BI raporlarını ortak bir kural setiyle denetleyip **100 üzerinden puanlayan** bir kalite aracı. Bir `.pbit` şablon dosyası yüklenir; veri modeli, sorgular, DAX ve görseller incelenir, her bulgu önem derecesi ve düzeltme önerisiyle raporlanır. İsteğe bağlı olarak yerel bir dil modeli (Ollama, varsayılan `qwen3:8b`) bulguları anlaşılır bir yol haritasına dönüştürür.

> Rapor kalitesini ölçmenin ortak bir standardı olmadığında değerlendirme inceleyen kişiye göre değişir ve hatalar yayından sonra fark edilir. Bu araç her rapora aynı kuralları uygular.

## Özellikler

- **Kural tabanlı puanlama:** Sonuç her zaman aynı kurallarla, tekrarlanabilir şekilde hesaplanır.
- **Önem dereceli bulgular:** Kritik, yüksek, orta, düşük ve bilgi notu olarak sıralanır. Her bulgunun bir düzeltme önerisi vardır.
- **AI yorumu (opsiyonel):** Yerel dil modeline tüm metadata değil, yalnızca kural motorunun bulguları ve kısa bir model özeti gönderilir. Ollama yoksa ya da yanıt vermezse analiz kural tabanlı olarak tamamlanır.
- **Web arayüzü ve komut satırı:** Tarayıcıdan sürükle-bırak ile ya da terminalden kullanılabilir.
- **HTML rapor:** Puan kartları, kategori dağılımı ve bulgu listesi içeren, PDF olarak indirilebilen bir rapor üretilir.
- **Veri dışarı çıkmaz:** Sunucu yalnızca `127.0.0.1` üzerinden erişilebilir, dil modeli bilgisayarda çalışır.

## Puanlama

Her kategori alt başlıklardan (kovalardan) oluşur. Her kova kendi puanıyla başlar ve içindeki bulguların kesintisi kadar düşer, 0'ın altına inmez. Böylece bir alandaki sorunlar başka bir alanın puanını etkilemez.

| Kategori | Puan | Alt başlıklar |
|---|---|---|
| **Veri Modellemesi** | 40 | Star schema 10 · N-N ilişkiler 8 · Çift yönlü filtre 8 · Kardinalite ve aktif/pasif 6 · İlişkisiz tablolar 4 · Calendar dimension 4 |
| **Sorgu + DAX + Veri Tipi** | 30 | SQL sorguları 8 · Veri tipi ve kullanılmayan kolonlar 12 · DAX 10 |
| **Görselleştirme** | 30 | Görsel yoğunluğu 12 · Grafik uygunluğu 10 · İsimlendirme 8 |

Raporda uygulanamayan bir bölüm varsa (örneğin hiç SQL sorgusu yoksa) o bölümün puanı aynı kategorideki diğer bölümlere orantılı olarak dağıtılır. Ağırlıklar `findings.py` içindeki `SCORE_MODEL` tablosundan değiştirilebilir.

| Genel skor | Durum |
|---|---|
| 85 ve üzeri | 🟢 Üst düzey — üretim ortamına hazır |
| 70 – 84 | 🟡 İyi — bazı iyileştirmeler gerekli |
| 50 – 69 | 🟠 Orta — önemli düzeltmeler gerekli |
| 50'nin altı | 🔴 Kritik — acil müdahale gerekli |

## Kurulum

Python 3.9 veya üzeri yeterli. Web arayüzü ve kural motoru yalnızca Python'un standart kütüphanesini kullanır.

AI yorumu istiyorsanız:

```bash
pip install -r requirements.txt     # ollama Python paketi
ollama pull qwen3:8b
```

Ollama kurulu değilse bu adımı atlayabilirsiniz, araç kural tabanlı çalışır.

## Kullanım

### Web arayüzü

```bash
python3 app.py
```

Tarayıcıda **http://127.0.0.1:8765** açılır. `.pbit` dosyasını sürükleyip bırakın, analiz bitince rapor açılır. macOS'ta `Baslat.command` dosyasına çift tıklayarak da başlatabilirsiniz, Ollama kapalıysa onu da açar.

| Parametre | Açıklama |
|---|---|
| `--port 8765` | Sunucu portu |
| `--model qwen3:8b` | Kullanılacak Ollama modeli |
| `--no-browser` | Tarayıcıyı otomatik açma |

Üretilen raporlar ve analiz geçmişi `reports/` klasöründe saklanır. Bu klasör analiz edilen raporların bilgilerini içerebileceği için Git'e eklenmez.

### Komut satırı

```bash
python3 main.py Test_0.pbit                       # kurallar + AI yorumu + HTML rapor
python3 main.py Test_0.pbit --no-ai               # sadece kural motoru
python3 main.py Test_0.pbit --json sonuc.json     # bulguları JSON olarak da kaydet
python3 main.py Test_0.pbit --model qwen3:14b     # farklı model
python3 main.py Test_0.pbit --no-html             # HTML rapor üretme
```

> `.pbit` dosyası yoksa: Power BI Desktop'ta **Dosya → Dışarı aktar → Power BI şablonu** ile kaydedin.

## Proje yapısı

| Dosya | Görevi |
|---|---|
| `app.py` | Yerel web sunucusu: yükleme, arka plan işleri, rapor ve geçmiş |
| `main.py` | Komut satırı giriş noktası |
| `pbit_parser.py` | `.pbit` arşivini açar; tablo, kolon, ilişki, measure ve rapor sayfalarını okur |
| `comprehensive_analyzer.py` | Kural motoru: tüm kontrolleri çalıştırır, puanı hesaplar |
| `findings.py` | Bulgu modeli, önem dereceleri ve `SCORE_MODEL` puan tablosu |
| `usage.py` | Kolon ve measure'ların gerçekten kullanılıp kullanılmadığını bulur |
| `naming.py` | İsimlendirme standardı: anlaşılır, PascalCase, Türkçe karakter içermeyen adlar |
| `visual_rules.py` | Görsel türünün gösterilen verinin yapısına uygunluğu |
| `agents.py` | Ollama ile AI yorumu katmanı |
| `report_html.py` | HTML rapor üretimi |
| `web/index.html` | Web arayüzü |
| `Test_0.pbit` | Denemek için örnek şablon (veri içermez) |

## Sınırlar

- `.pbit` dosyası veri satırı içermez. Bu yüzden kategori ya da dilim **sayısına** dayanan kontroller yapılamaz, görsel kontrolleri yalnızca görselin yapısına bakar.
- AI yorumu bulguları açıklar ve önceliklendirir, puanı değiştirmez. Puan her zaman kural motorundan gelir.
