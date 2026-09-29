(() => {
  'use strict';

  // Lista para o grupo: os ranchos salvos ficam no navegador de cada visitante
  // (sem login). O link mandado ao grupo leva os ranchos no endereço (/lista?r=a,b,c).
  const FAV_KEY = 'ranchos-favoritos';
  const FAV_MAX = 12;
  const readFavs = () => {
    try { const v = JSON.parse(localStorage.getItem(FAV_KEY)); return Array.isArray(v) ? v : []; }
    catch { return []; }
  };
  const writeFavs = (list) => { try { localStorage.setItem(FAV_KEY, JSON.stringify(list)); } catch { /* modo anônimo */ } };
  const listUrl = (favs) => `/lista?r=${favs.map(encodeURIComponent).join(',')}`;
  function syncFavs() {
    const favs = readFavs();
    document.querySelectorAll('[data-fav]').forEach((b) => {
      const on = favs.includes(b.dataset.fav);
      b.classList.toggle('on', on);
      b.setAttribute('aria-pressed', on ? 'true' : 'false');
      b.textContent = on ? b.dataset.on : b.dataset.off;
    });
    const bar = document.getElementById('favbar');
    if (bar) {
      const onListPage = !!document.getElementById('lista');
      bar.hidden = !favs.length || onListPage;
      document.getElementById('favbar-count').textContent =
        `♥ ${favs.length} ${favs.length === 1 ? 'rancho salvo' : 'ranchos salvos'}`;
      document.getElementById('favbar-link').href = listUrl(favs);
    }
  }
  document.addEventListener('click', (e) => {
    const b = e.target.closest('[data-fav]');
    if (!b) return;
    e.preventDefault();
    let favs = readFavs();
    const slug = b.dataset.fav;
    if (favs.includes(slug)) favs = favs.filter((s) => s !== slug);
    else if (favs.length >= FAV_MAX) { alert(`A lista vai até ${FAV_MAX} ranchos. Tire algum antes de salvar outro.`); return; }
    else {
      favs = [...favs, slug];
      countSave(slug);
    }
    writeFavs(favs);
    syncFavs();
  });
  // Avisa o site na primeira vez que este navegador salva o rancho (tirar e pôr de novo não soma).
  // O número aparece só no painel e no relatório do dono.
  const COUNTED_KEY = 'ranchos-contados';
  function countSave(slug) {
    let counted = [];
    try { counted = JSON.parse(localStorage.getItem(COUNTED_KEY)) || []; } catch { /* sem armazenamento */ }
    if (counted.includes(slug)) return;
    fetch(`/rancho/${encodeURIComponent(slug)}/salvou`, { method: 'POST', keepalive: true }).catch(() => {});
    try { localStorage.setItem(COUNTED_KEY, JSON.stringify([...counted, slug].slice(-200))); } catch { /* idem */ }
  }
  // /lista sem ranchos no endereço: abre a lista salva neste navegador
  if (document.getElementById('lista-vazia') && !new URLSearchParams(location.search).get('r')) {
    const favs = readFavs();
    if (favs.length) location.replace(listUrl(favs));
  }
  syncFavs();
  window.addEventListener('pageshow', syncFavs); // volta pelo botão "voltar" do celular
  document.querySelectorAll('[data-copy-text]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      try { await navigator.clipboard.writeText(btn.dataset.copyText); }
      catch { prompt('Copie o link:', btn.dataset.copyText); }
      const old = btn.textContent;
      btn.textContent = 'Link copiado';
      setTimeout(() => { btn.textContent = old; }, 1600);
    });
  });

  // Filtros: busca só a lista de resultados em segundo plano, sem recarregar a página
  const filters = document.getElementById('filters');
  const results = document.getElementById('results');
  if (filters) {
    const urlFor = () => {
      const params = new URLSearchParams();
      new FormData(filters).forEach((v, k) => {
        if (v && !(k === 'ordem' && v === 'destaque')) params.append(k, v); // sem vazios nem o padrão
      });
      const qs = params.toString();
      return filters.action.split('#')[0].split('?')[0] + (qs ? `?${qs}` : '');
    };
    let pending = null;
    const refresh = async (url) => {
      if (!results || !window.fetch) { location.href = `${url}#ranchos`; return; }
      if (pending) pending.abort();
      pending = new AbortController();
      results.classList.add('loading');
      try {
        const resp = await fetch(url, { signal: pending.signal });
        if (!resp.ok) throw new Error(resp.status);
        const doc = new DOMParser().parseFromString(await resp.text(), 'text/html');
        const fresh = doc.getElementById('results');
        if (!fresh) throw new Error('sem resultados');
        results.innerHTML = fresh.innerHTML;
        syncFavs(); // os cards novos vêm com o ♡ vazio
        history.replaceState(null, '', `${url}#ranchos`);
      } catch (err) {
        if (err.name !== 'AbortError') location.href = `${url}#ranchos`; // se falhar, faz do jeito antigo
      } finally {
        results.classList.remove('loading');
      }
    };
    filters.addEventListener('change', () => refresh(urlFor()));
    filters.addEventListener('submit', (e) => { e.preventDefault(); refresh(urlFor()); });
    // "Limpar filtros" e "Ver todos os ranchos" também sem recarregar
    results?.addEventListener('click', (e) => {
      const a = e.target.closest('a[href]');
      if (!a || new URL(a.href).pathname !== new URL(filters.action).pathname) return;
      e.preventDefault();
      filters.reset();
      [...filters.elements].forEach((el) => {
        if (el.tagName === 'SELECT') el.selectedIndex = 0;
        if (el.type === 'checkbox') el.checked = false;
      });
      refresh(urlFor());
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

  // Painel: gerador de link com etiqueta de origem (?utm_source=...)
  const lbSource = document.getElementById('lb-source');
  if (lbSource) {
    const page = document.getElementById('lb-page');
    const out = document.getElementById('lb-out');
    const build = () => {
      const src = lbSource.value.trim().toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '')
        .replace(/[^a-z0-9_-]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 40);
      out.value = src ? `${out.dataset.base}${page.value}?utm_source=${src}` : '';
    };
    lbSource.addEventListener('input', build);
    page.addEventListener('change', build);
  }

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
  // Envio em lotes: salva os dados do rancho e depois manda as fotos aos poucos,
  // para qualquer quantidade de fotos caber no limite por envio.
  const LOTE_MB = 20, LOTE_FOTOS = 15;
  function lotes(files) {
    const out = [];
    let atual = [], bytes = 0;
    for (const f of files) {
      if (atual.length && (atual.length >= LOTE_FOTOS || bytes + f.size > LOTE_MB * 1048576)) {
        out.push(atual); atual = []; bytes = 0;
      }
      atual.push(f); bytes += f.size;
    }
    if (atual.length) out.push(atual);
    return out;
  }
  async function postar(url, body, tentativas = 2) {
    for (let t = 1; ; t++) {
      try {
        const resp = await fetch(url, { method: 'POST', body });
        if (resp.ok) return resp;
        if (t >= tentativas || resp.status < 500) throw new Error(`erro ${resp.status}`);
      } catch (err) {
        if (t >= tentativas) throw err;
      }
      await new Promise((r) => setTimeout(r, 1500)); // espera um pouco e tenta de novo
    }
  }
  if (editForm && input && window.DataTransfer && window.createImageBitmap && window.fetch) {
    editForm.addEventListener('submit', async (e) => {
      if (!input.files.length) return; // sem fotos: salva do jeito normal
      e.preventDefault();
      const btn = editForm.querySelector('.sticky-save button');
      const status = document.getElementById('photo-count');
      btn.disabled = true;
      const files = [];
      const originais = [...input.files];
      for (let n = 0; n < originais.length; n++) {
        status.textContent = `Preparando foto ${n + 1} de ${originais.length}…`;
        files.push(await shrink(originais[n]));
      }
      const csrf = editForm.querySelector('[name=_csrf]').value;
      let enviadas = 0, added = 0, skipped = 0;
      try {
        // 1) dados do rancho, sem as fotos (cria o rancho se for novo e descobre o id)
        status.textContent = 'Salvando os dados do rancho…';
        const dados = new FormData(editForm);
        dados.delete('photos');
        const resp = await postar(editForm.action, dados, 1);
        const rid = (new URL(resp.url).pathname.match(/\/admin\/rancho\/(\d+)/) || [])[1];
        if (!rid) throw new Error('não consegui salvar o rancho');
        editForm.action = `/admin/rancho/${rid}`; // se precisar tentar de novo, não cria outro rancho
        // 2) fotos em lotes
        const grupos = lotes(files);
        for (let i = 0; i < grupos.length; i++) {
          const fim = enviadas + grupos[i].length;
          status.textContent = grupos.length > 1
            ? `Enviando lote ${i + 1} de ${grupos.length} (fotos ${enviadas + 1}–${fim} de ${files.length})…`
            : `Enviando ${files.length} foto(s)…`;
          const body = new FormData();
          body.append('_csrf', csrf);
          grupos[i].forEach((f) => body.append('photos', f));
          if (i === grupos.length - 1) {
            body.append('final', '1');
            body.append('prev_added', added);
            body.append('prev_skipped', skipped);
          }
          const data = await (await postar(`/admin/rancho/${rid}/fotos`, body)).json();
          added += data.added; skipped += data.skipped; enviadas = fim;
        }
        const destino = `/admin/rancho/${rid}`;
        if (location.pathname === destino) { location.hash = 'fotos'; location.reload(); } // mesmo endereço não recarrega sozinho
        else location.href = `${destino}#fotos`;
      } catch (err) {
        // deixa selecionadas só as que faltaram, para continuar de onde parou
        const resto = new DataTransfer();
        files.slice(enviadas).forEach((f) => resto.items.add(f));
        input.files = resto.files;
        status.textContent = enviadas
          ? `Parou no meio (${err.message}). ${enviadas} de ${files.length} fotos foram salvas; as ${files.length - enviadas} que faltam continuam selecionadas. Clique em Salvar rancho para continuar.`
          : `Não foi possível enviar (${err.message}). Confira a internet e clique em Salvar rancho de novo.`;
        btn.disabled = false;
      }
    });
  }
})();
