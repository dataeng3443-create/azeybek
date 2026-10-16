#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Kural motorunun bulgularını yorumlayan LLM katmanı (yerel Ollama).

Tasarım notları:
  * `ollama` paketi veya sunucusu yoksa sistem çökmez; `available()` False döner
    ve analiz tamamen kural tabanlı olarak devam eder.
  * LLM'e tüm metadata değil, kural motorunun ürettiği bulgular + kısa model
    özeti gönderilir. Böylece prompt küçük kalır ve yorum tespit edilen gerçek
    sorunlara bağlanır.
"""

import json
import re

# 16 GB Apple Silicon için önerilen varsayılan. Değiştirmek için: --model <ad>
DEFAULT_MODEL = "qwen3:8b"

THINK_BLOCK = re.compile(r'<think>.*?</think>', flags=re.DOTALL | re.IGNORECASE)

SEVERITY_LABELS = {
    'critical': 'KRİTİK',
    'high': 'YÜKSEK',
    'medium': 'ORTA',
    'low': 'DÜŞÜK',
    'info': 'BİLGİ',
}


class BIAgents:
    def __init__(self, model_name=DEFAULT_MODEL, timeout=180):
        self.model_name = model_name
        self.timeout = timeout
        self.last_error = None
        self._client = None
        self._available = None

    # --------------------------------------------------------- erişilebilirlik
    def _load_client(self):
        if self._client is not None:
            return self._client
        try:
            import ollama  # noqa: PLC0415 - bilinçli gecikmeli import
        except ImportError as exc:
            self.last_error = (
                "ollama paketi kurulu değil (pip install ollama). "
                f"Detay: {exc}"
            )
            return None
        self._client = ollama
        return self._client

    def available(self):
        """Model gerçekten çağrılabilir durumda mı? Sonuç önbelleğe alınır."""
        if self._available is not None:
            return self._available

        client = self._load_client()
        if client is None:
            self._available = False
            return False

        try:
            names = self._installed_model_names(client.list())
            if names and not self._model_installed(names):
                self.last_error = (
                    f"'{self.model_name}' modeli Ollama'da bulunamadı. "
                    f"Mevcut modeller: {', '.join(names)} "
                    f"(kurmak için: ollama pull {self.model_name})"
                )
                self._available = False
                return False
        except Exception as exc:
            self.last_error = f"Ollama sunucusuna ulaşılamadı ({exc}). 'ollama serve' çalışıyor mu?"
            self._available = False
            return False

        self._available = True
        self.last_error = None
        return True

    @staticmethod
    def _field(obj, key):
        """ollama<0.4 sözlük, ollama>=0.4 nesne döndürür; ikisini de okur."""
        if isinstance(obj, dict):
            return obj.get(key)
        return getattr(obj, key, None)

    def _installed_model_names(self, listing):
        names = []
        for item in self._field(listing, 'models') or []:
            name = self._field(item, 'model') or self._field(item, 'name')
            if name:
                names.append(name)
        return names

    def _model_installed(self, names):
        wanted = self.model_name
        if ':' in wanted:
            # 'qwen3:8b' tam eşleşmeli; 'qwen3:14b' kuruluysa yetmez
            return wanted in names
        # Etiketsiz ad ('llama3') -> 'llama3:latest' vb. herhangi bir etiket yeter
        return any(name.split(':')[0] == wanted for name in names)

    @staticmethod
    def _clean_output(text):
        """Reasoning modellerinin (qwen3, deepseek-r1) <think> bloğunu atar."""
        if not text:
            return text
        text = THINK_BLOCK.sub('', text)
        # Kapanmamış <think> varsa (cevap kesilmişse) o noktadan sonrasını at
        text = text.split('<think>')[0]
        return text.strip()

    # ------------------------------------------------------------------ çağrı
    def run_task(self, role, task, data=None):
        """Tek seferlik serbest prompt. Hata durumunda None döner."""
        client = self._load_client()
        if client is None:
            return None

        prompt_parts = [f"ROLE: {role}", f"TASK: {task}"]
        if data is not None:
            prompt_parts.append(f"DATA: {json.dumps(data, ensure_ascii=False)}")
        prompt = "\n".join(prompt_parts)

        request = {
            'model': self.model_name,
            'messages': [{'role': 'user', 'content': prompt}],
            'options': {'temperature': 0.2, 'num_ctx': 8192},
        }
        try:
            try:
                # Düşünme modunu kapat: daha hızlı ve çıktıda <think> olmaz (ollama>=0.9)
                response = client.chat(**request, think=False)
            except TypeError:
                # Eski python paketi 'think' parametresini tanımıyor
                response = client.chat(**request)
            message = self._field(response, 'message')
            content = self._field(message, 'content') if message is not None else None
            return self._clean_output(content or "") or None
        except Exception as exc:
            self.last_error = f"AI çağrısı başarısız: {exc}"
            return None

    # ------------------------------------------------------------- yorumlama
    @staticmethod
    def _format_findings(findings, limit=18):
        lines = []
        for finding in findings[:limit]:
            severity = SEVERITY_LABELS.get(finding.severity, finding.severity.upper())
            line = f"- [{severity}] ({finding.category}) {finding.title}"
            if finding.detail:
                line += f" :: {finding.detail}"
            if finding.evidence:
                sample = ', '.join(str(e) for e in finding.evidence[:4])
                if len(finding.evidence) > 4:
                    sample += f" (+{len(finding.evidence) - 4} tane daha)"
                line += f" :: örnekler: {sample}"
            lines.append(line)
        if len(findings) > limit:
            lines.append(f"- (+{len(findings) - limit} ek bulgu listelenmedi)")
        return "\n".join(lines) if lines else "- Kural motoru belirgin bir bulgu üretmedi."

    @staticmethod
    def _format_model_summary(metadata):
        profile = metadata.get('profile', {})
        layout = metadata.get('report_layout', {})
        summary = {
            "tablo_sayisi": metadata.get('visible_table_count', metadata.get('table_count', 0)),
            "iliski_sayisi": metadata.get('rel_count', 0),
            "measure_sayisi": metadata.get('measure_count', 0),
            "kolon_sayisi": metadata.get('column_count', 0),
            "rol_tespit_yontemi": profile.get('method'),
            "fact_tablolari": profile.get('facts', []),
            "dimension_tablolari": profile.get('dimensions', []),
            "izole_tablolar": profile.get('isolated', []),
            "tarih_dimension": profile.get('date_dimensions', []),
            "otomatik_tarih_tablolari": len(profile.get('auto_date_tables', [])),
            "sayfa_sayisi": layout.get('page_count', 0),
            "gorsel_sayisi": layout.get('visual_count', 0),
        }
        return json.dumps(summary, ensure_ascii=False, indent=1)

    @staticmethod
    def _format_schema(metadata, max_columns_per_table=25):
        """Modeldeki gerçek tablo/kolon/measure adları: LLM'in ad uydurmasını önler."""
        lines = []
        for table in metadata.get('visible_tables', metadata.get('tables', [])):
            cols = [f"{c['name']} ({c.get('data_type') or c.get('t')})" for c in table['cols'][:max_columns_per_table]]
            if len(table['cols']) > max_columns_per_table:
                cols.append(f"+{len(table['cols']) - max_columns_per_table} kolon")
            lines.append(f"- '{table['name']}': {', '.join(cols)}")
            for measure in table.get('measures', []):
                lines.append(f"    measure [{measure['name']}]")
        return "\n".join(lines) or "- (tablo yok)"

    @staticmethod
    def _format_breakdown(breakdown):
        lines = []
        for data in breakdown.values():
            lines.append(f"- {data['label']}: {data['score']:g}/{data['max']}")
            for bucket in data['buckets']:
                if bucket.get('applicable', True):
                    lines.append(f"    - {bucket['label']}: {bucket['score']:g}/{bucket['max']:g}")
                else:
                    lines.append(f"    - {bucket['label']}: uygulanmadı ({bucket.get('note')})")
        return "\n".join(lines)

    @staticmethod
    def _format_visuals(visual_reviews, limit=25):
        """Sorunlu görselleri ayrıntılı, uygun olanları sadece sayı olarak verir (prompt kısa kalsın)."""
        verdicts = {'suggest': 'öneri var', 'error': 'uygun değil'}
        reviews = [r for r in visual_reviews or [] if r.get('verdict') != 'skip']
        flagged = [r for r in reviews if r['verdict'] in verdicts]
        flagged.sort(key=lambda r: 0 if r['verdict'] == 'error' else 1)
        lines = []
        for review in flagged[:limit]:
            line = (f"- [{verdicts[review['verdict']]}] {review['page']} / "
                    f"{review['type_label']}: {review.get('field_summary', '')}")
            for _, text, _ in review.get('issues', []):
                line += f" | kural: {text}"
            lines.append(line)
        ok_count = len(reviews) - len(flagged)
        if ok_count:
            lines.append(f"- {ok_count} görsel kurallara göre uygun (yorum gerekmez)")
        return "\n".join(lines) or "- (görsel yok)"

    def explain_findings(self, metadata, findings, breakdown, total_score, visual_reviews=None):
        """Bulguları Power BI uzmanı gözüyle yorumlar ve aksiyon planı üretir."""
        if not self.available():
            return None

        task = f"""
Aşağıda bir Power BI (.pbit) raporunun kural tabanlı denetim sonucu var. Genel skor: {total_score:.1f}/100

PUAN DAĞILIMI:
{self._format_breakdown(breakdown)}

MODEL ÖZETİ:
{self._format_model_summary(metadata)}

MODEL ŞEMASI (gerçek tablo ve kolon adları; kodda SADECE bunları kullan):
{self._format_schema(metadata)}

KURAL MOTORUNUN BULGULARI:
{self._format_findings(findings)}

GÖRSELLER (alan anlamları: zaman / kategori / coğrafya / ölçü):
{self._format_visuals(visual_reviews)}

Görevin, bu bulguları bir Power BI mimarı gibi yorumlamak. Kurallar:
1. Yeni sorun UYDURMA. Sadece yukarıdaki bulgulara, şemaya ve görsel listesine dayan. Puan verme.
2. Kod örneklerinde yalnızca MODEL ŞEMASI'ndaki tablo ve kolon adlarını yaz. Şemada olmayan bir kolon
   kullanma. Yeni bir tablo öneriyorsan (örn. Tarih tablosu) bunu açıkça "yeni tablo" diye belirt.
3. SQL (kaynak sorgu) ile DAX (measure, calculated column) önerilerini birbirine karıştırma.
4. Measure örneklerinde EARLIER kullanma; gerekirse VAR kullan.
5. Aynı öneriyi veya aynı kod bloğunu birden fazla bulgu için tekrarlama.
6. Çıktıyı şu başlıklarla ver:
   ## Teşhis
   En kritik 3 sorunun raporda yarattığı somut etkiyi (yavaşlık, yanlış toplam, bakım zorluğu)
   her biri için 1-2 cümleyle açıkla.
   ## Düzeltme Adımları
   Bulguları "Veri Modeli", "SQL", "DAX" alt başlıklarında grupla; her biri için uygulanabilir adım ve
   gerekiyorsa kısa kod örneği yaz.
   ## Görsel Önerileri
   "uygun değil" veya "öneri var" işaretli görseller için neden ve hangi görselin kullanılması
   gerektiğini yaz. Uygun görseller için bir şey yazma.
   ## Öncelik Sırası
   Maddeleri etki/efor dengesine göre sırala ve her birinin neden o sırada olduğunu tek cümleyle yaz.
7. Türkçe yaz, kısa ve teknik ol, giriş ve kapanış cümlesi yazma.
"""
        return self.run_task("Senior Power BI Architect", task)

    @staticmethod
    def find_unknown_references(text, metadata):
        """AI metnindeki Tablo[Kolon] referanslarını şemayla karşılaştırır.

        Modelde var olan bir tabloda olmayan kolon/measure geçiyorsa listeler.
        Modelde hiç olmayan tablolar (AI'nin önerdiği yeni tablolar) sayılmaz.
        """
        if not text:
            return []
        from pbit_parser import fold_name  # döngüsel importu önlemek için burada

        known = {}
        for table in metadata.get('tables', []):
            fields = {fold_name(c['name']) for c in table['cols']}
            fields |= {fold_name(m['name']) for m in table.get('measures', [])}
            known[fold_name(table['name'])] = fields
        all_measures = {fold_name(m['name']) for m in metadata.get('measures', [])}

        unknown = []
        pattern = re.compile(r"(?:'([^'\n]{1,80})'|\b([A-Za-z_ÇĞİÖŞÜçğıöşü][\wÇĞİÖŞÜçğıöşü]{0,60}))\[([^\]\n]{1,80})\]")
        for match in pattern.finditer(text):
            table_name = match.group(1) or match.group(2)
            field_name = match.group(3)
            table_key = fold_name(table_name)
            if table_key not in known:
                continue  # modelde olmayan tablo: AI yeni tablo öneriyor olabilir
            field_key = fold_name(field_name)
            if field_key in known[table_key] or field_key in all_measures:
                continue
            ref = f"{table_name}[{field_name}]"
            if ref not in unknown:
                unknown.append(ref)
        return unknown

