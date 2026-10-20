/*
 * SciPlan AssistantPet
 *
 * Replaceable module: swap the image path, tip list, or click handler here
 * without touching task planning or chat code. The widget stores its position
 * locally and distinguishes a click from a drag.
 */
class AssistantPet {
  constructor({root, image, bubble, size=92, asset='/assets/assistant_character.png', onSpeak=()=>{}}) {
    this.root = root; this.image = image; this.bubble = bubble; this.onSpeak = onSpeak;
    this.image.src = asset; this.setSize(size); this.dragging = false; this.moved = false;
    this.restorePosition(); this.bind();
  }
  setSize(size) {
    this.size = Math.max(56, Math.min(160, Number(size) || 92));
    this.root.style.setProperty('--pet-size', `${this.size}px`);
  }
  setAsset(asset) { if (asset) this.image.src = asset; }
  restorePosition() {
    const saved = JSON.parse(localStorage.getItem('sciplan-pet-position') || 'null');
    if (saved && Number.isFinite(saved.left) && Number.isFinite(saved.top)) {
      this.root.style.left = `${saved.left}px`; this.root.style.top = `${saved.top}px`;
      this.root.style.right = 'auto'; this.root.style.bottom = 'auto';
    }
  }
  savePosition() {
    const rect = this.root.getBoundingClientRect();
    localStorage.setItem('sciplan-pet-position', JSON.stringify({left: Math.round(rect.left), top: Math.round(rect.top)}));
  }
  bind() {
    this.root.addEventListener('pointerdown', e => {
      this.dragging = true; this.moved = false; this.startX = e.clientX; this.startY = e.clientY;
      const rect = this.root.getBoundingClientRect(); this.originLeft = rect.left; this.originTop = rect.top;
      this.root.setPointerCapture(e.pointerId); this.root.classList.add('dragging');
    });
    this.root.addEventListener('pointermove', e => {
      if (!this.dragging) return;
      const dx = e.clientX - this.startX, dy = e.clientY - this.startY;
      if (Math.abs(dx) + Math.abs(dy) > 5) this.moved = true;
      const left = Math.max(4, Math.min(window.innerWidth - this.root.offsetWidth - 4, this.originLeft + dx));
      const top = Math.max(70, Math.min(window.innerHeight - this.root.offsetHeight - 4, this.originTop + dy));
      this.root.style.left = `${left}px`; this.root.style.top = `${top}px`; this.root.style.right = 'auto'; this.root.style.bottom = 'auto';
    });
    this.root.addEventListener('pointerup', e => {
      if (!this.dragging) return; this.dragging = false; this.root.releasePointerCapture(e.pointerId); this.root.classList.remove('dragging');
      if (this.moved) this.savePosition(); else this.onSpeak();
    });
  }
  speak(text) {
    this.bubble.textContent = text; this.bubble.classList.remove('hidden');
    this.placeBubble();
    clearTimeout(this.hideTimer); this.hideTimer = setTimeout(() => this.bubble.classList.add('hidden'), 5200);
  }
  placeBubble() {
    const pet = this.root.getBoundingClientRect();
    const bubble = this.bubble;
    const pad = 10;
    bubble.style.position = 'absolute'; bubble.style.right = 'auto'; bubble.style.bottom = 'auto';
    const bw = bubble.offsetWidth || 210, bh = bubble.offsetHeight || 60;
    let left, top, side;
    if (window.innerWidth - pet.right >= bw + pad) { left = this.root.offsetWidth + pad; top = (this.root.offsetHeight - bh) / 2; side = 'right'; }
    else if (pet.top >= bh + 84) { left = (this.root.offsetWidth - bw) / 2; top = -bh - pad; side = 'top'; }
    else if (pet.left >= bw + pad) { left = -bw - pad; top = (this.root.offsetHeight - bh) / 2; side = 'left'; }
    else { left = (this.root.offsetWidth - bw) / 2; top = this.root.offsetHeight + pad; side = 'bottom'; }
    bubble.style.left = `${left}px`;
    bubble.style.top = `${top}px`;
    bubble.dataset.side = side;
  }
}
