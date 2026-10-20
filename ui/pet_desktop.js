const petShell = document.querySelector('#petShell');
const petImage = document.querySelector('#petImage');
const petBubble = document.querySelector('#petBubble');
const petCapture = document.querySelector('#petCapture');
const petInput = document.querySelector('#petInput');
const petReview = document.querySelector('#petReview');
const petMenu = document.querySelector('#petMenu');
const composeActions = document.querySelector('#petComposeActions');
const reviewActions = document.querySelector('#petReviewActions');
let petItems = [];
let bubbleTimer;
let dragStart = null;
let dragOrigin = null;
let moved = false;
let suppressClick = false;

function say(text) {
  petBubble.textContent = text;
  petBubble.classList.remove('hidden');
  clearTimeout(bubbleTimer);
  bubbleTimer = setTimeout(() => petBubble.classList.add('hidden'), 5200);
}
function resetReview() {
  petItems = [];
  petInput.style.height = '92px';
  petInput.classList.remove('hidden');
  petReview.classList.add('hidden');
  petReview.innerHTML = '';
  composeActions.classList.remove('hidden');
  reviewActions.classList.add('hidden');
}
function toggleCapture(show) {
  petCapture.classList.toggle('hidden', !show);
  if (show) { petBubble.classList.add('hidden'); resetReview(); window.pywebview?.api?.focus_window?.(); setTimeout(() => petInput.focus(), 80); }
  else resetReview();
}
function hideMenu() { petMenu.classList.add('hidden'); }
function renderPetReview(items) {
  petItems = items || [];
  petReview.innerHTML = petItems.map((item, i) => `<div class="pet-review-row" data-pet-index="${i}"><input data-field="title" value="${String(item.title || '未命名任务').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\"/g,'&quot;')}" /><select data-field="board_id"><option value="paper" ${item.board_id==='paper'?'selected':''}>论文</option><option value="research" ${item.board_id==='research'?'selected':''}>课题</option><option value="grant" ${item.board_id==='grant'?'selected':''}>标书</option><option value="misc" ${item.board_id==='misc'?'selected':''}>杂事</option></select><input data-field="due" type="date" value="${item.due || ''}" /><select data-field="priority"><option value="1" ${Number(item.priority)===1?'selected':''}>P1</option><option value="2" ${Number(item.priority)===2?'selected':''}>P2</option><option value="3" ${Number(item.priority)===3?'selected':''}>P3</option><option value="4" ${Number(item.priority)===4?'selected':''}>P4</option></select></div>`).join('');
  petInput.classList.add('hidden'); petReview.classList.remove('hidden'); composeActions.classList.add('hidden'); reviewActions.classList.remove('hidden');
}

petImage.addEventListener('pointerdown', async e => {
  if (e.button !== 0 || !window.pywebview?.api?.get_position) return;
  dragStart = {x: e.screenX, y: e.screenY}; moved = false; dragOrigin = await window.pywebview.api.get_position(); petImage.setPointerCapture?.(e.pointerId);
});
petImage.addEventListener('pointermove', e => {
  if (!dragStart || !dragOrigin || !window.pywebview?.api?.move_window) return;
  const dx = e.screenX - dragStart.x, dy = e.screenY - dragStart.y;
  if (Math.abs(dx) + Math.abs(dy) <= 5) return;
  moved = true; window.pywebview.api.move_window(dragOrigin.x + dx, dragOrigin.y + dy);
});
petImage.addEventListener('pointerup', e => { if (moved) suppressClick = true; dragStart = null; dragOrigin = null; petImage.releasePointerCapture?.(e.pointerId); });
petImage.onclick = () => { if (suppressClick) { suppressClick = false; return; } toggleCapture(petCapture.classList.contains('hidden')); };

petShell.addEventListener('contextmenu', e => { e.preventDefault(); petMenu.style.left = `${Math.max(4, Math.min(e.offsetX, 202))}px`; petMenu.style.top = `${Math.max(4, Math.min(e.offsetY, 160))}px`; petMenu.classList.remove('hidden'); });
document.addEventListener('pointerdown', e => { if (!petMenu.contains(e.target)) hideMenu(); });
document.querySelector('#petHide').onclick = async () => { hideMenu(); await fetch('/api/desktop/hide', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'}); };
document.querySelector('#petCancel').onclick = () => toggleCapture(false);
document.querySelector('#petPaste').onclick = async () => {
  const text = await readClipboardText();
  if (!insertClipboardText(text)) say('剪贴板里没有可粘贴的文字。');
};
document.querySelector('#petReviewBack').onclick = () => { resetReview(); petInput.focus(); };
petInput.oninput = () => { petInput.style.height = 'auto'; petInput.style.height = `${Math.min(190, Math.max(92, petInput.scrollHeight))}px`; };
function insertClipboardText(text) {
  if (!text) return false;
  const start = petInput.selectionStart ?? petInput.value.length;
  const end = petInput.selectionEnd ?? start;
  petInput.value = petInput.value.slice(0, start) + text + petInput.value.slice(end);
  const cursor = start + text.length;
  petInput.selectionStart = cursor; petInput.selectionEnd = cursor;
  petInput.dispatchEvent(new Event('input', {bubbles: true}));
  return true;
}
async function readClipboardText() {
  try {
    const text = await navigator.clipboard.readText();
    if (text) return text;
  } catch (err) {}
  try {
    if (window.pywebview?.api?.read_clipboard) return await window.pywebview.api.read_clipboard();
  } catch (err) {}
  return '';
}
petInput.addEventListener('paste', e => {
  const text = e.clipboardData?.getData('text/plain') || '';
  if (text) return;
  e.preventDefault();
  readClipboardText().then(insertClipboardText);
});
petInput.addEventListener('keydown', e => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'v') {
    e.preventDefault();
    readClipboardText().then(insertClipboardText);
  }
});
petInput.onkeydown = e => { if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') document.querySelector('#petSave').click(); if (e.key === 'Escape') toggleCapture(false); };
document.querySelector('#petSave').onclick = async () => {
  const text = petInput.value.trim(); if (!text) return say('先把刚接到的任务粘贴给我吧。');
  const button = document.querySelector('#petSave'); button.disabled = true; button.textContent = '识别中…';
  try { const res = await fetch('/api/pet-capture', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({text})}); const data = await res.json(); if (!res.ok || !data.ok) throw new Error(data.error || '识别失败'); if (!data.items?.length) throw new Error('没有识别到可执行任务'); await fetch('/api/desktop/pending', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({items: data.items, mode: data.mode, text})}); await fetch('/api/desktop/show-main', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'}); petInput.value = ''; toggleCapture(false); say('已送到 SciPlan 主窗口，请审核后确认入库。'); }
  catch (err) { say(err.message || '暂时无法识别，请稍后再试。'); }
  finally { button.disabled = false; button.textContent = '发送到 SciPlan'; }
};
document.querySelector('#petReviewConfirm').onclick = async () => {
  const rows = [...petReview.querySelectorAll('[data-pet-index]')];
  const items = rows.map(row => { const item = {...petItems[Number(row.dataset.petIndex)]}; row.querySelectorAll('[data-field]').forEach(el => { item[el.dataset.field] = el.value; }); item.priority = Number(item.priority) || 3; item.due = item.due || null; return item; });
  const res = await fetch('/api/pet-confirm', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({items})}); const data = await res.json();
  if (!res.ok || !data.ok) return say('确认入库失败，请稍后再试。'); toggleCapture(false); say(`已确认加入 ${data.count} 条任务`);
};

function applyConfig(data) { const c = data.config || {}; if (c.pet_image) petImage.src = c.pet_image; const size = Math.max(72, Math.min(160, Number(c.pet_size) || 104)); document.documentElement.style.setProperty('--pet-size', `${size}px`); }
fetch('/api/state').then(r => r.json()).then(applyConfig).catch(() => {}); setInterval(() => fetch('/api/state').then(r => r.json()).then(applyConfig).catch(() => {}), 5000);
