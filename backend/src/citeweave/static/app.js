'use strict';
const $ = id => document.getElementById(id);
let current = null, busy = false, timer = null, toastTimer = null;
const historyKey = 'citeweave.history.v1';
let history = [];
try { const saved = JSON.parse(localStorage.getItem(historyKey) || '[]'); if (Array.isArray(saved)) history = saved.filter(x => x && Array.isArray(x.blocks) && Array.isArray(x.sources) && Array.isArray(x.images)).slice(0, 12); } catch {}
function el(tag, className, text) { const node = document.createElement(tag); if (className) node.className = className; if (text !== undefined) node.textContent = text; return node; }
function link(url, className, text) {
  const node = el('a', className, text);
  try { const parsed = new URL(url, location.origin); if (!['http:', 'https:'].includes(parsed.protocol)) return el('span', className, text); node.href = parsed.href; node.target = '_blank'; node.rel = 'noopener noreferrer'; } catch { return el('span', className, text); }
  return node;
}
function toast(message) { $('toast').textContent = message; $('toast').classList.remove('hidden'); clearTimeout(toastTimer); toastTimer = setTimeout(() => $('toast').classList.add('hidden'), 2500); }
function safeImage(url, alt) {
  const image = el('img'); const target = link(url);
  if (!target.href) return el('p', 'empty-image', '图片暂时不可用，可查看原始来源。');
  image.src = target.href; image.alt = alt || '来源图片'; image.loading = 'lazy'; image.decoding = 'async'; image.referrerPolicy = 'no-referrer';
  image.onerror = () => image.replaceWith(el('p', 'empty-image', '图片暂时不可用，可查看原始来源。'));
  return image;
}
function inlineText(node, text) {
  // Source text is never interpreted as HTML. Only bold and code spans are styled.
  const parts = String(text).split(/(\*\*[^*]+\*\*|`[^`]+`)/g);
  for (const part of parts) {
    if (part.startsWith('**') && part.endsWith('**')) node.append(el('strong', '', part.slice(2, -2)));
    else if (part.startsWith('`') && part.endsWith('`')) node.append(el('code', '', part.slice(1, -1)));
    else node.append(document.createTextNode(part));
  }
}
function remember(data) {
  history = [data, ...history.filter(x => x.query !== data.query)].slice(0, 12);
  try { localStorage.setItem(historyKey, JSON.stringify(history)); } catch { history = history.slice(0, 3); try { localStorage.setItem(historyKey, JSON.stringify(history)); } catch {} }
  renderHistory();
}
function renderHistory() {
  $('history').replaceChildren();
  if (!history.length) { $('history').append(el('p', 'history-empty', '你最近的搜索会保存在此浏览器中。')); return; }
  for (const item of history) { const button = el('button', 'history-item', item.query); button.title = item.query; if (current && current.query === item.query) button.classList.add('active'); button.onclick = () => { if (busy) return; render(item, true); }; $('history').append(button); }
  const clear = el('button', 'history-item', '清除本地记录'); clear.onclick = () => { history = []; localStorage.removeItem(historyKey); renderHistory(); toast('本地搜索记录已清除'); }; $('history').append(clear);
}
function render(data, fromHistory = false) {
  current = data; $('query').value = data.query; $('urls').value = (data.request_urls || []).join('\n'); $('verify').checked = data.verify_images !== false; $('hero').classList.add('compact'); $('result').classList.remove('hidden'); $('answerBody').replaceChildren(); $('sources').replaceChildren();
  $('resultKind').textContent = fromHistory ? '本地记录' : data.cache_hit ? '近期缓存' : '联网回答';
  $('answerMeta').textContent = `${data.sources.length} 个来源 · ${Number(data.total_seconds || data.seconds || 0).toFixed(1)}s`;
  const sources = new Map(data.sources.map(s => [s.id, s])); const images = new Map(data.images.map(i => [i.id, i]));
  $('answerBody').append(el('h2', '', data.title || data.query));
  if (fromHistory) $('answerBody').append(el('p', 'notice', '这是此浏览器保存的回答。需要最新资料时，点击右上角重新检索。'));
  if (data.retrieval_errors && data.retrieval_errors.length) $('answerBody').append(el('p', 'notice', '部分网页暂时无法读取，回答使用了其余可访问的来源。'));
  for (const block of data.blocks) {
    const paragraph = el('p', 'answer-paragraph'); inlineText(paragraph, block.text); $('answerBody').append(paragraph);
    const citations = el('div', 'citations');
    for (const id of block.source_ids || []) { const source = sources.get(id); if (source) citations.append(link(source.url, 'citation', `↗ ${Number(id.slice(1)) + 1}`)); }
    $('answerBody').append(citations);
    const image = images.get(block.image_id);
    if (image) {
      const figure = el('figure', 'figure'); const button = el('button', 'image-button'); button.setAttribute('aria-label', '放大查看图片'); button.append(safeImage(image.render_url || image.url, block.image_caption || image.caption));
      button.onclick = () => { const target = link(image.render_url || image.url); if (!target.href) return; $('zoomImage').src = target.href; $('zoomImage').alt = block.image_caption || image.caption || '来源图片'; $('lightbox').showModal(); };
      const caption = el('figcaption'); caption.append(link(image.source_url || image.url, '', '图片来源 ↗'));
      const details = el('details', 'caption-details'); details.append(el('summary', '', '查看图片说明'), el('p', '', block.image_caption || image.caption || '来源未提供说明。')); caption.append(details); figure.append(button, caption); $('answerBody').append(figure);
    }
  }
  const heading = el('div', 'source-heading', '参考来源'); heading.append(el('span', '', data.sources.length)); $('sources').append(heading);
  for (const source of data.sources) {
    const card = link(source.url, 'source-card'); const preview = source.preview_image || data.images.find(i => i.source_id === source.id);
    if (preview) card.append(safeImage(preview.render_url || preview.url, preview.caption || source.title));
    let domain = source.url; try { domain = new URL(source.url).hostname.replace(/^www\./, ''); } catch {}
    const domainLine = el('div', 'source-domain'); domainLine.append(el('span', 'source-number', Number(source.id.slice(1)) + 1), document.createTextNode(domain));
    card.append(domainLine, el('div', 'source-title', source.title), el('span', 'external', '↗')); $('sources').append(card);
  }
  renderHistory(); $('result').scrollIntoView({behavior: 'smooth', block: 'start'});
}
function markdown(data) {
  const sources = new Map(data.sources.map(s => [s.id, s])); const images = new Map(data.images.map(i => [i.id, i])); const parts = [`# ${data.title || data.query}`];
  for (const block of data.blocks) {
    parts.push(block.text);
    const refs = (block.source_ids || []).map(id => sources.get(id)).filter(Boolean);
    if (refs.length) parts.push(refs.map(s => `[${s.title.replace(/[\[\]]/g, '')}](${s.url})`).join(' · '));
    const image = images.get(block.image_id);
    if (image) { parts.push(`![${String(block.image_caption || image.caption || '').replace(/[\[\]\n]/g, ' ')}](${image.url})`); if (image.source_url) parts.push(`[图片来源](${image.source_url})`); }
  }
  parts.push('## 参考来源', ...data.sources.map(s => `- [${s.title}](${s.url})`)); return parts.join('\n\n');
}
async function search(refresh = false) {
  if (busy) return;
  const query = $('query').value.trim(); const urls = $('urls').value.split('\n').map(x => x.trim()).filter(Boolean);
  if (query.length < 2) { $('query').focus(); return; }
  if (urls.length > 5) { toast('最多指定 5 个网页来源'); return; }
  busy = true; $('submit').disabled = true; $('refreshAnswer').disabled = true; $('error').classList.add('hidden'); $('result').classList.add('hidden'); $('loading').classList.remove('hidden'); $('hero').classList.add('compact');
  const start = Date.now(); timer = setInterval(() => $('elapsed').textContent = ` 已等待 ${Math.floor((Date.now() - start) / 1000)} 秒。`, 1000);
  try {
    const response = await fetch('/api/search', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({query, urls, verify_images: $('verify').checked, refresh})});
    const data = await response.json();
    if (response.status === 401) { $('accessDialog').showModal(); throw Error('请先连接工作区，再开始搜索。'); }
    if (response.status === 409) throw Error('当前工作区正在处理另一个搜索，请稍后重试。');
    if (response.status === 429) throw Error('搜索过于频繁，请在一分钟后重试。');
    if (!response.ok) throw Error(typeof data.detail === 'string' ? data.detail : '搜索未能完成，请调整问题或指定网页来源后重试。');
    data.request_urls = urls; data.verify_images = $('verify').checked; render(data); remember(data);
  } catch (error) { $('error').textContent = error.message; $('error').classList.remove('hidden'); }
  finally { clearInterval(timer); $('elapsed').textContent = ''; busy = false; $('submit').disabled = false; $('refreshAnswer').disabled = false; $('loading').classList.add('hidden'); }
}
$('searchForm').onsubmit = event => { event.preventDefault(); search(); };
$('query').onkeydown = event => { if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) { event.preventDefault(); search(); } };
$('sourceToggle').onclick = () => { const expanded = $('sourceToggle').getAttribute('aria-expanded') !== 'true'; $('sourceToggle').setAttribute('aria-expanded', String(expanded)); $('sourceOptions').classList.toggle('hidden', !expanded); };
document.querySelectorAll('[data-query]').forEach(button => button.onclick = () => { $('query').value = button.dataset.query; $('query').focus(); });
$('newSearch').onclick = () => { if (busy) return; current = null; $('query').value = ''; $('urls').value = ''; $('hero').classList.remove('compact'); $('result').classList.add('hidden'); $('error').classList.add('hidden'); renderHistory(); window.scrollTo({top: 0, behavior: 'smooth'}); $('query').focus(); };
$('copyAnswer').onclick = async () => { if (!current) return; try { await navigator.clipboard.writeText(markdown(current)); toast('已复制回答与来源'); } catch { toast('浏览器不允许复制，请使用导出功能。'); } };
$('exportAnswer').onclick = () => { if (!current) return; const url = URL.createObjectURL(new Blob([markdown(current)], {type: 'text/markdown;charset=utf-8'})); const a = el('a'); a.href = url; a.download = 'citeweave-' + new Date().toISOString().slice(0, 10) + '.md'; document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000); };
$('refreshAnswer').onclick = () => { if (!current) return; $('query').value = current.query; $('urls').value = (current.request_urls || []).join('\n'); $('verify').checked = current.verify_images !== false; search(true); };
$('closeZoom').onclick = () => $('lightbox').close(); $('lightbox').onclick = event => { if (event.target === $('lightbox')) $('lightbox').close(); };
$('connectionButton').onclick = () => $('accessDialog').showModal();
$('accessForm').onsubmit = async event => {
  event.preventDefault();
  try { const response = await fetch('/api/session', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({token: $('accessToken').value})}); if (!response.ok) throw Error('访问令牌无效，请联系工作区管理员。'); $('accessToken').value = ''; $('accessDialog').close(); $('connection').textContent = '工作区已连接'; toast('工作区已连接，可以开始搜索'); }
  catch (error) { $('accessError').textContent = error.message; }
};
fetch('/api/status').then(r => r.json()).then(data => { $('connection').textContent = data.authentication_required ? '等待连接工作区' : '工作区已连接'; $('connectionButton').classList.toggle('hidden', !data.authentication_enabled); $('connectionButton').textContent = data.authentication_required ? '连接' : '管理'; if (data.authentication_required) $('accessDialog').showModal(); }).catch(() => $('connection').textContent = '暂时无法连接');
renderHistory();
