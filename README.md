# AI Projeleri

Power BI ve iş zekâsı (BI) odaklı, yerel LLM (Ollama) destekli dört prototip.

| Klasör | Ne yapar | Teknoloji |
|---|---|---|
| [`LLM_Destekli_BI_Paneli`](LLM_Destekli_BI_Paneli/) | **LLM-Powered BI Dashboard** — doğal dilde sorulan soruyu doğrulanmış DAX sorgusuna çevirir, sentetik bir SSAS Tabular modeli üzerinde çalıştırır ve otomatik dashboard üretir. | Python, Streamlit, Plotly, Ollama |
| [`BI_Skorlama`](BI_Skorlama/) | **BI Skorlama** — bir Power BI `.pbit` dosyasını modelleme, sorgu ve görselleştirme açısından analiz edip puanlar ve bulgu raporu üretir. | Python, Ollama (opsiyonel) |
| [`SSAS_Generator`](SSAS_Generator/) | Power BI `.pbit` şablonundan SQL Server Analysis Services (SSAS) Tabular modeli (`model.bim`) üretir. | .NET 8, Blazor |
| [`BI_UX_Designer`](BI_UX_Designer/) | **BI UX Designer** — bir Power BI raporunun sayfa düzenini yapay zekâ ile yeniden tasarlar ve yeni bir `.pbit` üretir. | Python, Ollama |

Her projenin kurulum ve çalıştırma adımları kendi klasöründeki README / başlatma dosyasındadır.

> Gizli ayarlar (`.env`), sanal ortamlar, derleme çıktıları ve analiz edilen raporların çıktıları depoya dahil edilmez (bkz. `.gitignore`).
