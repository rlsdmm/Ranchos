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

  // Reordenar fotos arrastando (mouse: a foto toda; celular: pelo ⠿, pra não atrapalhar a rolagem)
  const grid = document.getElementById('photo-grid');
  if (grid) {
    const status = document.getElementById('order-status');
    const statusText = status.innerHTML;
    const order = () => [...grid.children].map((li) => li.dataset.id).join(',');
    let dragged = null, before = '', timer = null;

    grid.addEventListener('pointerdown', (e) => {
      const li = e.target.closest('li[data-id]');
      if (!li || e.button > 0) return;
      const onHandle = e.target.closest('.drag-handle');
      if (!onHandle && (e.pointerType !== 'mouse' || e.target.closest('button, form'))) return;
      e.preventDefault();
      dragged = li;
      before = order();
      li.classList.add('dragging');
      grid.classList.add('is-dragging');
      try { grid.setPointerCapture(e.pointerId); } catch { /* sem captura, segue funcionando */ }
    });

    grid.addEventListener('pointermove', (e) => {
      if (!dragged) return;
      const over = document.elementFromPoint(e.clientX, e.clientY)?.closest('#photo-grid > li');
      if (over && over !== dragged) {
        const items = [...grid.children];
        grid.insertBefore(dragged, items.indexOf(over) > items.indexOf(dragged) ? over.nextSibling : over);
      }
      // rolagem automática perto das bordas da tela
      if (e.clientY < 60) window.scrollBy(0, -12);
      else if (e.clientY > innerHeight - 60) window.scrollBy(0, 12);
    });

    const drop = async () => {
      if (!dragged) return;
      dragged.classList.remove('dragging');
      grid.classList.remove('is-dragging');
      dragged = null;
      const now = order();
      if (now === before) return;
      clearTimeout(timer);
      status.textContent = 'Salvando a nova ordem…';
      try {
        const body = new URLSearchParams({ _csrf: grid.dataset.csrf, ordem: now });
        const resp = await fetch(grid.dataset.orderUrl, { method: 'POST', body });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok || !data.ok) throw new Error(data.erro || 'Não foi possível salvar.');
        status.textContent = 'Ordem salva ✓';
        timer = setTimeout(() => { status.innerHTML = statusText; }, 2500);
      } catch (err) {
        status.textContent = `${err.message} Recarregue a página e tente de novo.`;
      }
    };
    grid.addEventListener('pointerup', drop);
    grid.addEventListener('pointercancel', drop);
  }

  // Reduz as fotos no navegador antes de enviar: o servidor guarda no máximo 1800 px mesmo,
  // o envio fica bem mais rápido e cabe no limite de ~32 MB por envio do Firebase/Cloud Run.
  const editForm = document.getElementById('edit-form');
  const MAX_PX = 2000;
  async function shrink(file) {
    if (!file.type.startsWith('image/') || file.size < 400 * 1024) return file;
    try {
      const bmp = await createImageBitmap(file, { imageOrientation: 'from-image' });
      const scale = Math.min(1, MAX_PX / Math.max(bmp.width, bmp.height));
      const canvas = document.createElement('canvas');
      canvas.width = Math.round(bmp.width * scale);
      canvas.height = Math.round(bmp.height * scale);
      canvas.getContext('2d').drawImage(bmp, 0, 0, canvas.width, canvas.height);
      bmp.close();
      const blob = await new Promise((res) => canvas.toBlob(res, 'image/jpeg', 0.88));
      if (!blob || blob.size >= file.size) return file;
      return new File([blob], file.name.replace(/\.\w+$/, '') + '.jpg', { type: 'image/jpeg' });
    } catch {
      return file; // formato que o navegador não abre (ex.: HEIC no Chrome): o servidor decide
    }
  }
  if (editForm && input && window.DataTransfer && window.createImageBitmap) {
    editForm.addEventListener('submit', async (e) => {
      if (!input.files.length || editForm.dataset.ready) return;
      e.preventDefault();
      const btn = editForm.querySelector('.sticky-save button');
      const status = document.getElementById('photo-count');
      btn.disabled = true;
      const dt = new DataTransfer();
      const files = [...input.files];
      for (let n = 0; n < files.length; n++) {
        status.textContent = `Preparando foto ${n + 1} de ${files.length}…`;
        dt.items.add(await shrink(files[n]));
      }
      input.files = dt.files;
      status.textContent = `Enviando ${files.length} foto(s)…`;
      editForm.dataset.ready = '1';
      editForm.submit();
    });
  }
})();
