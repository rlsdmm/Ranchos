(() => {
  'use strict';

  // Filters submit as soon as something changes
  const filters = document.getElementById('filters');
  if (filters) {
    filters.addEventListener('change', () => {
      // drop empty params so URLs stay clean
      [...filters.elements].forEach((el) => { if (el.tagName === 'SELECT' && !el.value) el.disabled = true; });
      filters.submit();
    });
  }

  // Gallery lightbox
  const gallery = document.querySelector('[data-gallery]');
  const lb = document.getElementById('lightbox');
  if (gallery && lb) {
    const items = [...gallery.querySelectorAll('[data-full]')];
    const img = lb.querySelector('img');
    const count = lb.querySelector('.lb-count');
    let i = 0;
    let startX = null;
    const show = (n) => {
      i = (n + items.length) % items.length;
      img.src = items[i].dataset.full;
      img.alt = items[i].querySelector('img').alt;
      count.textContent = `${i + 1} / ${items.length}`;
    };
    const open = (n) => { show(n); lb.hidden = false; document.body.style.overflow = 'hidden'; lb.querySelector('.lb-close').focus(); };
    const close = () => { lb.hidden = true; document.body.style.overflow = ''; items[i].focus(); };
    items.forEach((el, n) => el.addEventListener('click', () => open(n)));
    lb.querySelector('.lb-close').addEventListener('click', close);
    lb.querySelector('.lb-prev').addEventListener('click', () => show(i - 1));
    lb.querySelector('.lb-next').addEventListener('click', () => show(i + 1));
    lb.addEventListener('click', (e) => { if (e.target === lb) close(); });
    document.addEventListener('keydown', (e) => {
      if (lb.hidden) return;
      if (e.key === 'Escape') close();
      if (e.key === 'ArrowLeft') show(i - 1);
      if (e.key === 'ArrowRight') show(i + 1);
    });
    lb.addEventListener('touchstart', (e) => { startX = e.touches[0].clientX; }, { passive: true });
    lb.addEventListener('touchend', (e) => {
      if (startX === null) return;
      const dx = e.changedTouches[0].clientX - startX;
      if (Math.abs(dx) > 50) show(dx < 0 ? i + 1 : i - 1);
      startX = null;
    });
  }

  // Confirm before destructive admin actions
  document.querySelectorAll('form[data-confirm]').forEach((f) => {
    f.addEventListener('submit', (e) => { if (!confirm(f.dataset.confirm)) e.preventDefault(); });
  });

  // Copy buttons
  document.querySelectorAll('[data-copy]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const el = document.querySelector(btn.dataset.copy);
      try { await navigator.clipboard.writeText(el.value); }
      catch { el.select(); document.execCommand('copy'); }
      const old = btn.textContent;
      btn.textContent = 'Copiado';
      setTimeout(() => { btn.textContent = old; }, 1600);
    });
  });

  // Photo picker feedback
  const input = document.getElementById('photo-input');
  if (input) {
    input.addEventListener('change', () => {
      const n = input.files.length;
      document.getElementById('photo-count').textContent =
        n ? `${n} foto(s) selecionada(s). Clique em Salvar rancho para enviar.` : 'Nenhuma foto selecionada.';
    });
  }
})();
