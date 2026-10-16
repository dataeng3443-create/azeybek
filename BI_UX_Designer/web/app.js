const $ = id => document.getElementById(id);
let selected = null, reference = null, designMode = 'improve', health = null, activeJob = null, stage = 'upload', starting = false, startedAt = 0, pollTimer = null, clockTimer = null;
const stages = ['upload', 'processing', 'ready', 'error'];
const chartNames = {clusteredBarChart:'Çubuk grafik',barChart:'Yığılmış çubuk',clusteredColumnChart:'Sütun grafik',columnChart:'Yığılmış sütun',lineChart:'Çizgi grafik',pieChart:'Pasta grafik',donutChart:'Halka grafik',tableEx:'Tablo',pivotTable:'Matris',slicer:'Filtre',card:'KPI kartı'};
const modeLabels = {improve: 'Görselleştirmeyi iyileştir', blank: 'Sıfırdan Tasarım Uygula', reference: 'Resme Uygun Görsel Tasarım'};
function showDecisions(result) {
  const list = $('decision-list'); list.replaceChildren();
  for (const page of result.decisions || []) {
    for (const choice of page.visuals) {
      const li = document.createElement('li');
      const title = document.createElement('strong'); title.textContent = choice.title;
      const description = document.createElement('span'); description.textContent = `${chartNames[choice.chart_type] || choice.chart_type} · ${choice.reason}`;
      li.append(title, description); list.append(li);
    }
  }
  $('design-decisions').hidden = !list.children.length;
}
function showModelNote(result) {
  const note = $('model-note');
  const fallback = (result.model_log || []).find(entry => !entry.model_used);
  const blank = result.mode === 'blank';
  $('kept-label').textContent = blank ? 'Aynı' : 'Korundu'; $('kept-sub').textContent = blank ? 'veri modeli' : 'analitik yapı';
  if (result.model_used === false) { note.textContent = 'Model yanıtı kullanılamadı; tasarım kural tabanlı motorla tamamlandı. ' + (fallback?.note || ''); note.hidden = false; }
  else if (fallback) { note.textContent = 'Bazı sayfalarda model yanıtı yerine kural tabanlı tasarım kullanıldı.'; note.hidden = false; }
  else note.hidden = true;
}
function showState(next) {
  stage = next;
  for (const s of stages) $(`${s}-state`).hidden = s !== next;
  const current = next === 'ready' ? 2 : next === 'upload' ? 0 : 1;
  ['upload', 'design', 'ready'].forEach((name, index) => {
    const element = $(`step-${name}`);
    element.className = index < current ? 'done' : index === current ? 'active' : '';
    if (index === current) element.setAttribute('aria-current', 'step'); else element.removeAttribute('aria-current');
  });
}
function error(message) { $('upload-error').textContent = message; $('upload-error').hidden = !message; }
function updateStart() { $('start-button').disabled = !selected || !health?.ready || (designMode === 'reference' && !reference); }
function setMode(mode) {
  designMode = mode; error('');
  document.querySelectorAll('.mode-card').forEach(card => card.classList.toggle('selected', card.querySelector('input').value === mode));
  $('reference-upload').hidden = mode !== 'reference'; $('start-label').textContent = modeLabels[mode]; updateStart();
}
function setFile(file) {
  if (stage === 'processing') return;
  error('');
  if (file && (!file.name.toLowerCase().endsWith('.pbit') || !file.size || file.size > 50 * 1024 * 1024)) {
    error('Lütfen 50 MB’dan küçük, boş olmayan bir .pbit dosyası seçin.');
    return;
  }
  selected = file;
  $('selected-file').hidden = !file;
  if (file) { $('filename').textContent = file.name; $('filesize').textContent = file.size < 1024 * 1024 ? `${(file.size / 1024).toFixed(1)} KB` : `${(file.size / (1024 * 1024)).toFixed(1)} MB`; }
  else $('file-input').value = '';
  updateStart();
}
function setReference(file) {
  error('');
  if (file && (!/\.png$/i.test(file.name) || !file.size || file.size > 12 * 1024 * 1024)) { error('Lütfen 12 MB’dan küçük, boş olmayan bir PNG dosyası seçin.'); return; }
  reference = file; $('selected-reference').hidden = !file;
  if (file) { $('reference-name').textContent = file.name; $('reference-size').textContent = `${(file.size / (1024 * 1024)).toFixed(1)} MB`; }
  else $('reference-input').value = '';
  updateStart();
}
async function checkHealth() {
  try {
    const response = await fetch('/api/health');
    if (!response.ok) throw new Error();
    health = await response.json();
    $('model-status').textContent = health.ready ? 'Qwen hazır' : 'Qwen bağlantısı yok';
    $('model-badge').title = `${health.model} · ${health.message}`;
    $('model-badge').className = `model-badge ${health.ready ? 'online' : 'offline'}`;
    if (!health.ready && stage === 'upload') error(health.message);
    else if (health.ready && !selected) error('');
  } catch { health = null; $('model-status').textContent = 'Bağlantı kurulamadı'; $('model-badge').className = 'model-badge offline'; }
  updateStart();
}
function stopTimers() { clearTimeout(pollTimer); clearInterval(clockTimer); }
function reset() { stopTimers(); activeJob = null; history.replaceState(null, '', '/'); showState('upload'); setFile(null); setReference(null); setMode('improve'); checkHealth(); }
async function startDesign() {
  if (starting || stage === 'processing') return;
  if (!selected) throw new Error('Önce bir .pbit dosyası seçin.');
  if (designMode === 'reference' && !reference) throw new Error('Bu mod için bir PNG referans görseli seçin.');
  starting = true;
  $('start-button').disabled = true;
  await checkHealth();
  if (!health?.ready) { starting = false; error(health?.message || 'Uygulamaya bağlanılamıyor.'); return; }
  error(''); showState('processing'); startedAt = Date.now();
  starting = false;
  $('processing-file').textContent = selected.name; $('processing-message').textContent = designMode === 'reference' ? 'Referans görsel ve şablon hazırlanıyor.' : 'Şablonunuz yükleniyor.'; $('elapsed').textContent = '00:00';
  clockTimer = setInterval(() => { const elapsed = Math.floor((Date.now() - startedAt) / 1000); $('elapsed').textContent = `${String(Math.floor(elapsed / 60)).padStart(2, '0')}:${String(elapsed % 60).padStart(2, '0')}`; }, 1000);
  try {
    const response = await fetch('/api/jobs', { method: 'POST', headers: {'Content-Type': 'application/octet-stream', 'X-Filename': encodeURIComponent(selected.name), 'X-UX-Mode': designMode, 'X-UX-Token': health.token}, body: selected });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Dosya yüklenemedi.');
    activeJob = result.id; history.replaceState(null, '', `/?job=${activeJob}`);
    if (designMode === 'reference') {
      const imageResponse = await fetch(`/api/jobs/${activeJob}/reference`, {method: 'POST', headers: {'Content-Type': 'image/png', 'X-Reference-Filename': encodeURIComponent(reference.name), 'X-UX-Token': health.token}, body: reference});
      const imageResult = await imageResponse.json(); if (!imageResponse.ok) throw new Error(imageResult.error || 'Referans görsel yüklenemedi.');
    }
    poll();
  } catch (e) { fail(e.message); }
}
function fail(message) { stopTimers(); $('job-error').textContent = message; showState('error'); }
async function poll() {
  try {
    const response = await fetch(`/api/jobs/${activeJob}`);
    const job = await response.json();
    if (!response.ok) throw new Error(job.error || 'İşlem durumu alınamadı.');
    $('processing-file').textContent = job.filename;
    if (job.created_at) {
      const seconds = Math.max(0, Math.floor(Date.now() / 1000 - job.created_at));
      $('elapsed').textContent = `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
    }
    if (job.stage === 'ready') {
      stopTimers(); $('page-count').textContent = job.result.pages; $('visual-count').textContent = job.result.visuals;
      showDecisions(job.result); showModelNote(job.result);
      $('download-button').href = job.download; $('download-button').download = job.filename.replace(/\.pbit$/i, '_UX.pbit'); showState('ready'); return;
    }
    if (job.stage === 'error') { fail(job.message); return; }
    $('processing-message').textContent = job.message;
  } catch (e) { fail(e.message || 'Bağlantı kesildi.'); return; }
  pollTimer = setTimeout(poll, 1200);
}
$('file-input').addEventListener('change', e => setFile(e.target.files[0]));
$('reference-input').addEventListener('change', e => setReference(e.target.files[0]));
$('remove-reference').addEventListener('click', () => setReference(null));
document.querySelectorAll('input[name="design-mode"]').forEach(input => input.addEventListener('change', () => setMode(input.value)));
$('remove-file').addEventListener('click', () => setFile(null));
for (const name of ['dragover', 'dragenter']) $('dropzone').addEventListener(name, e => { e.preventDefault(); $('dropzone').classList.add('dragging'); });
for (const name of ['dragleave', 'drop']) $('dropzone').addEventListener(name, e => { e.preventDefault(); $('dropzone').classList.remove('dragging'); });
$('dropzone').addEventListener('drop', e => { if (e.dataTransfer.files.length !== 1) return error('Her işlem için tek bir .pbit dosyası seçin.'); setFile(e.dataTransfer.files[0]); });
$('start-button').addEventListener('click', () => startDesign().catch(e => error(e.message)));
$('retry-button').addEventListener('click', () => { showState('upload'); startDesign().catch(e => error(e.message)); });
for (const id of ['new-file', 'change-file']) $(id).addEventListener('click', reset);
checkHealth(); setInterval(() => { if (stage === 'upload') checkHealth(); }, 15000);
const resumeJob = new URLSearchParams(location.search).get('job');
if (resumeJob && /^[a-f0-9]{32}$/.test(resumeJob)) { activeJob = resumeJob; showState('processing'); poll(); }
if (document.modelContext?.registerTool) {
  const lifecycle = new AbortController();
  const register = tool => { try { Promise.resolve(document.modelContext.registerTool(tool, {signal: lifecycle.signal})).catch(() => {}); } catch {} };
  register({name: 'get_design_status', title: 'Tasarım durumunu oku', description: 'Seçili dosyayı ve bu sayfadaki tasarım işleminin durumunu okur.', inputSchema: {type: 'object', properties: {}, additionalProperties: false}, annotations: {readOnlyHint: true}, execute: async input => { if (!input || Object.keys(input).length) throw new Error('Parametre beklenmiyor.'); return {stage, filename: selected?.name || null, job: activeJob}; }});
  register({name: 'start_selected_template_design', title: 'Seçili şablonun tasarımını başlat', description: 'Kullanıcının bu sayfada seçtiği PBIT dosyasını yerel Qwen modeliyle işler. Dosya seçimi gereklidir.', inputSchema: {type: 'object', properties: {}, additionalProperties: false}, annotations: {readOnlyHint: false}, execute: async input => { if (!input || Object.keys(input).length) throw new Error('Parametre beklenmiyor.'); if (!selected || !health?.ready || stage !== 'upload') throw new Error('Hazır Qwen bağlantısı ve seçili şablon gerekiyor.'); await startDesign(); return {stage, job: activeJob}; }});
  addEventListener('pagehide', () => lifecycle.abort(), {once: true});
}
