(() => {
  'use strict';

  // Aviso que aparece no topo e some sozinho, no lugar do alert() do navegador
  // (que no celular trava a tela e dentro do Instagram/Facebook às vezes nem aparece)
  let toastTimer;
  function toast(msg, ms = 4000) {
    let el = document.getElementById('toast');
    if (!el) {
      el = document.createElement('div');
      el.id = 'toast';
      el.className = 'toast';
      el.setAttribute('role', 'status');
      el.setAttribute('aria-live', 'polite');
      el.addEventListener('click', () => el.classList.remove('show'));
      document.body.appendChild(el);
    }
    el.textContent = msg;
    void el.offsetWidth; // aplica o estado escondido antes, para a entrada animar
    el.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove('show'), ms);
  }
  // Cópia sem a API nova (navegador antigo ou navegador embutido de app)
  function legacyCopy(text) {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.setAttribute('readonly', '');
    ta.style.cssText = 'position:fixed;top:0;left:0;opacity:0';
    document.body.appendChild(ta);
    ta.select();
    let ok = false;
    try { ok = document.execCommand('copy'); } catch { /* sem suporte */ }
    ta.remove();
    return ok;
  }

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
    else if (favs.length >= FAV_MAX) { toast(`A lista vai até ${FAV_MAX} ranchos. Tire algum antes de salvar outro.`); return; }
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
      const text = btn.dataset.copyText;
      let ok = true;
      try { await navigator.clipboard.writeText(text); }
      catch { ok = legacyCopy(text); }
      if (!ok) { toast(`Não deu para copiar sozinho. O link é: ${text}`, 10000); return; }
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

  // Galeria: botões de ambiente filtram as fotos na página; a tela cheia mostra o que está filtrado.
  // Camadas por cima da página (tela de fotos, foto única): o "voltar" do celular fecha a de cima
  // em vez de sair do anúncio. Fechar pela tela também passa pelo histórico, para ficar igual.
  const layers = [];
  let scrollLocks = 0;
  const lockScroll = (on) => {
    scrollLocks = Math.max(0, scrollLocks + (on ? 1 : -1));
    document.body.style.overflow = scrollLocks ? 'hidden' : '';
  };
  const pushLayer = (closeFn) => { layers.push(closeFn); history.pushState({ layer: layers.length }, ''); };
  const closeTopLayer = () => { if (layers.length) history.back(); };
  window.addEventListener('popstate', () => { const fn = layers.pop(); if (fn) fn(); });

  // Foto única: setas, arrastar para o lado, pinça/toque duplo para zoom, arrastar para baixo fecha
  function makeViewer(box) {
    const img = box.querySelector('img');
    const count = box.querySelector('.lb-count');
    let items = [], i = 0, back = null;
    let scale = 1, tx = 0, ty = 0;
    const apply = (anim) => {
      img.style.transition = anim ? 'transform .22s ease' : 'none';
      img.style.transform = `translate(${tx}px, ${ty}px) scale(${scale})`;
    };
    const reset = (anim) => { scale = 1; tx = 0; ty = 0; box.style.backgroundColor = ''; apply(anim); };
    const clampPan = () => { // não deixa a foto ampliada sair inteira da tela
      const mx = (img.offsetWidth * (scale - 1)) / 2, my = (img.offsetHeight * (scale - 1)) / 2;
      tx = Math.max(-mx, Math.min(mx, tx));
      ty = Math.max(-my, Math.min(my, ty));
    };
    const show = (n) => {
      i = (n + items.length) % items.length;
      reset(false);
      img.src = items[i].full;
      img.alt = items[i].alt || '';
      count.textContent = items[i].text || `${i + 1} / ${items.length}`;
      box.querySelector('.lb-prev').hidden = box.querySelector('.lb-next').hidden = items.length < 2;
    };
    const hide = () => { box.hidden = true; lockScroll(false); if (back) back.focus({ preventScroll: true }); };
    const open = (list, n, from) => {
      items = list; back = from || null;
      show(n);
      box.hidden = false;
      lockScroll(true);
      pushLayer(hide);
      box.querySelector('.lb-close').focus({ preventScroll: true });
    };
    box.querySelector('.lb-close').addEventListener('click', closeTopLayer);
    box.querySelector('.lb-prev').addEventListener('click', () => show(i - 1));
    box.querySelector('.lb-next').addEventListener('click', () => show(i + 1));
    box.addEventListener('click', (e) => { if (e.target === box) closeTopLayer(); });
    img.addEventListener('dblclick', () => { scale = scale > 1 ? 1 : 2.5; tx = ty = 0; apply(true); });
    document.addEventListener('keydown', (e) => {
      if (box.hidden) return;
      if (e.key === 'Escape') closeTopLayer();
      if (e.key === 'ArrowLeft') show(i - 1);
      if (e.key === 'ArrowRight') show(i + 1);
    });
    // Toque: 1 dedo arrasta (lado = trocar foto, baixo = fechar, ampliada = mover); 2 dedos = zoom
    let sx = 0, sy = 0, dx = 0, dy = 0, axis = null, pinch = null, lastTap = 0, moved = false;
    const dist = (t) => Math.hypot(t[0].clientX - t[1].clientX, t[0].clientY - t[1].clientY);
    box.addEventListener('touchstart', (e) => {
      if (e.target.closest('button')) return;
      if (e.touches.length === 2) { pinch = { d: dist(e.touches), s: scale }; return; }
      sx = e.touches[0].clientX; sy = e.touches[0].clientY; dx = dy = 0; axis = null; moved = false;
    }, { passive: true });
    box.addEventListener('touchmove', (e) => {
      if (e.target.closest('button')) return;
      e.preventDefault(); // a página de trás não rola nem dá zoom
      if (pinch && e.touches.length === 2) {
        scale = Math.max(1, Math.min(4, pinch.s * dist(e.touches) / pinch.d));
        clampPan(); apply(false); return;
      }
      if (e.touches.length !== 1) return;
      const nx = e.touches[0].clientX, ny = e.touches[0].clientY;
      const ddx = nx - sx - dx, ddy = ny - sy - dy;
      dx = nx - sx; dy = ny - sy;
      if (Math.abs(dx) > 6 || Math.abs(dy) > 6) moved = true;
      if (scale > 1) { tx += ddx; ty += ddy; clampPan(); apply(false); return; }
      if (!axis && moved) axis = Math.abs(dx) > Math.abs(dy) ? 'x' : 'y';
      if (axis === 'x') { tx = dx; apply(false); }
      if (axis === 'y' && dy > 0) {
        ty = dy; apply(false);
        box.style.backgroundColor = `rgba(8,20,19,${Math.max(0.35, 0.94 - dy / 500)})`;
      }
    }, { passive: false });
    box.addEventListener('touchend', (e) => {
      if (pinch) { if (e.touches.length < 2) { pinch = null; if (scale < 1.05) reset(true); } return; }
      if (e.target.closest('button')) return;
      if (!moved) { // toque duplo amplia/volta
        const now = Date.now();
        if (now - lastTap < 300) { scale = scale > 1 ? 1 : 2.5; tx = ty = 0; apply(true); lastTap = 0; }
        else lastTap = now;
        return;
      }
      if (scale > 1) return;
      if (axis === 'y' && dy > 110) { closeTopLayer(); return; }
      if (axis === 'x' && Math.abs(dx) > 60 && items.length > 1) { show(dx < 0 ? i + 1 : i - 1); return; }
      reset(true);
    });
    return { open };
  }

  const lb = document.getElementById('lightbox');
  const viewer = lb ? makeViewer(lb) : null;
  const toItem = (el, text) => ({ full: el.dataset.full, alt: el.querySelector('img')?.alt, text });

  // Tela "Todas as fotos" do rancho: tocar na galeria abre ela, já na foto tocada
  const tour = document.getElementById('tour');
  let openTour = null;
  if (tour && viewer) {
    const tItems = [...tour.querySelectorAll('[data-full]')];
    const tList = tItems.map((el) => toItem(el, el.dataset.text));
    tItems.forEach((el, k) => el.addEventListener('click', () => viewer.open(tList, k, el)));
    let back = null;
    const hideTour = () => { tour.hidden = true; lockScroll(false); if (back) back.focus({ preventScroll: true }); };
    // pid: abre já nessa foto; area: abre no começo desse ambiente
    openTour = (pid, from, area) => {
      back = from || null;
      tour.hidden = false;
      lockScroll(true);
      pushLayer(hideTour);
      const target = (pid && tour.querySelector(`.tour-item[data-pid="${pid}"]`))
        || (area && document.getElementById(`tour-${area}`));
      if (target) target.scrollIntoView({ block: pid ? 'center' : 'start' });
      else tour.scrollTop = 0;
      tour.querySelector('.tour-close').focus({ preventScroll: true });
    };
    tour.querySelector('.tour-close').addEventListener('click', closeTopLayer);
    tour.querySelectorAll('[data-tour-jump]').forEach((b) => b.addEventListener('click', () => {
      document.getElementById(b.dataset.tourJump)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }));
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && !tour.hidden && lb.hidden) closeTopLayer();
    });
    document.querySelectorAll('[data-tour-open]').forEach((b) => b.addEventListener('click', (e) => {
      e.stopPropagation();
      openTour(null, b);
    }));
  }

  const gallery = document.querySelector('[data-gallery]');
  if (gallery && viewer) {
    const all = [...gallery.querySelectorAll('[data-full]')];
    const countTag = gallery.querySelector('.g-count');
    const chips = [...document.querySelectorAll('[data-area-filter]')];
    let items = all;
    const filter = (area) => {
      items = area ? all.filter((el) => el.dataset.area === area) : all;
      // As do ambiente vão para a frente (a grade do computador mostra as 5 primeiras); as outras somem.
      [...items, ...all.filter((el) => !items.includes(el))].forEach((el) => gallery.insertBefore(el, countTag));
      all.forEach((el) => {
        el.hidden = !items.includes(el);
        el.classList.toggle('g-main', el === items[0]);
      });
      gallery.className = gallery.className.replace(/g-n\d/, `g-n${Math.min(items.length, 5)}`);
      if (countTag) { countTag.textContent = `${items.length} fotos`; countTag.hidden = items.length <= 5; }
      gallery.scrollLeft = 0;
      chips.forEach((c) => c.setAttribute('aria-pressed', String(c.dataset.areaFilter === area)));
    };
    // Rancho: o botão do ambiente abre a tela de fotos nele ("Todas" abre do começo).
    // Sem a tela (não deveria acontecer), continua filtrando a galeria.
    chips.forEach((c) => c.addEventListener('click', () => {
      if (openTour) openTour(null, c, c.dataset.areaFilter);
      else filter(c.dataset.areaFilter);
    }));
    const open = (el) => {
      if (openTour) { openTour(el.dataset.pid, el); return; } // rancho: tela com todas as fotos
      // profissional: foto única, passando pelo que está na tela (cardápio e fotos do trabalho)
      const list = items.map((x, k) => {
        const c = x.dataset.caption; // nome do prato, no cardápio
        return toItem(x, `${c ? c + ' · ' : ''}${k + 1} / ${items.length}`);
      });
      viewer.open(list, items.indexOf(el), el);
    };
    all.forEach((el) => el.addEventListener('click', () => open(el)));
  }

  // Painel: mostra o que foi escolhido no campo de foto (no celular, sem isso parece que nada aconteceu)
  document.querySelectorAll('.upload input[type=file]').forEach((input) => {
    const label = input.parentElement.querySelector('span');
    const original = label.textContent;
    input.addEventListener('change', () => {
      const files = [...input.files];
      input.parentElement.querySelector('.upload-preview')?.remove();
      if (!files.length) { label.textContent = original; return; }
      label.textContent = files.length === 1 ? '✓ Foto escolhida' : `✓ ${files.length} fotos escolhidas`;
      if (files.length === 1 && files[0].type.startsWith('image/')) {
        const img = document.createElement('img');
        img.className = 'upload-preview';
        img.alt = '';
        img.src = URL.createObjectURL(files[0]);
        input.parentElement.appendChild(img);
      }
    });
  });

  // Painel: ambiente da foto salva sozinho ao escolher
  document.querySelectorAll('form.photo-area select').forEach((sel) => {
    sel.addEventListener('change', async () => {
      const form = sel.form;
      const ok = form.querySelector('.photo-area-ok');
      ok.textContent = '…';
      try {
        const resp = await fetch(form.action, { method: 'POST', body: new FormData(form), headers: { 'X-Requested-With': 'fetch' } });
        ok.textContent = resp.ok ? '✓' : 'erro';
      } catch (e) {
        ok.textContent = 'erro';
      }
    });
  });

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

  // Agenda: navegação entre os meses (1 por vez no celular, 2 na tela grande)
  document.querySelectorAll('[data-cal]').forEach((cal) => {
    const months = [...cal.querySelectorAll('.cal-month')];
    const prev = cal.querySelector('.cal-prev'), next = cal.querySelector('.cal-next');
    const pos = cal.querySelector('.cal-pos');
    const wide = matchMedia('(min-width: 760px)');
    let i = 0;
    const show = () => {
      const per = wide.matches ? 2 : 1;
      i = Math.max(0, Math.min(i, months.length - per));
      months.forEach((m, n) => { m.hidden = n < i || n >= i + per; });
      prev.disabled = i === 0;
      next.disabled = i + per >= months.length;
      pos.textContent = `${i + 1}${per > 1 ? '–' + (i + per) : ''} de ${months.length} meses`;
    };
    prev.addEventListener('click', () => { i -= wide.matches ? 2 : 1; show(); });
    next.addEventListener('click', () => { i += wide.matches ? 2 : 1; show(); });
    wide.addEventListener('change', show);
    show();
  });

  const fmtDay = (iso) => iso.split('-').reverse().slice(0, 2).join('/');
  const daysBetween = (a, b) => { // datas ISO de a até b, inclusive
    const out = [];
    for (let d = new Date(`${a}T12:00:00`); d <= new Date(`${b}T12:00:00`); d.setDate(d.getDate() + 1)) {
      out.push(d.toISOString().slice(0, 10));
    }
    return out;
  };

  // Agenda pública: turista toca na chegada e na saída; o botão do WhatsApp leva as datas
  const pubCal = document.querySelector('[data-cal="public"]');
  if (pubCal) {
    const dayBtn = (iso) => pubCal.querySelector(`[data-day="${iso}"]`);
    const box = document.getElementById('sel-dates');
    const hint = document.getElementById('sel-hint');
    const waLinks = [...document.querySelectorAll('.js-wa')];
    const waBase = waLinks.map((a) => a.getAttribute('href'));
    let start = null, end = null;
    const paint = () => {
      pubCal.querySelectorAll('.cal-day.sel, .cal-day.in-range').forEach((b) => b.classList.remove('sel', 'in-range'));
      if (start) {
        daysBetween(start, end || start).forEach((iso) => dayBtn(iso)?.classList.add('in-range'));
        dayBtn(start)?.classList.add('sel');
        if (end) dayBtn(end)?.classList.add('sel');
      }
      const qs = start ? `?de=${start}${end ? `&ate=${end}` : ''}` : '';
      waLinks.forEach((a, n) => a.setAttribute('href', waBase[n] + qs));
      if (box) {
        box.hidden = !start;
        box.querySelector('.js-sel-text').textContent = start
          ? (end ? `${fmtDay(start)} a ${fmtDay(end)}` : `${fmtDay(start)} (toque na data de saída)`) : '';
      }
      if (hint) hint.hidden = !!start;
    };
    pubCal.addEventListener('click', (e) => {
      const b = e.target.closest('.cal-day');
      if (!b || b.disabled) return;
      const iso = b.dataset.day;
      if (b.classList.contains('busy')) { b.blur(); return; } // ocupado: não seleciona
      if (!start || end || iso < start) { start = iso; end = null; }
      else if (iso === start) { start = null; }
      else if (daysBetween(start, iso).some((d) => dayBtn(d)?.classList.contains('busy'))) {
        toast('Tem dia ocupado no meio desse período. Escolha outras datas.');
        start = iso; end = null;
      } else { end = iso; }
      paint();
    });
    box?.querySelector('.js-sel-clear').addEventListener('click', () => { start = end = null; paint(); });
  }

  // Agenda do painel: dono toca no dia para marcar/liberar (ou marca um período)
  const editCal = document.querySelector('[data-cal="edit"]');
  const agenda = document.getElementById('agenda');
  if (editCal && agenda) {
    const status = document.getElementById('agenda-status');
    const rangeBox = document.getElementById('agenda-range');
    const dayBtn = (iso) => editCal.querySelector(`[data-day="${iso}"]`);
    let rangeStart = null;
    const save = async (days, busy) => {
      days.forEach((iso) => dayBtn(iso)?.classList.toggle('busy', busy)); // muda na hora...
      status.textContent = 'Salvando…';
      try {
        const body = new URLSearchParams({ _csrf: agenda.dataset.csrf, days: days.join(','), busy: busy ? '1' : '0' });
        const resp = await fetch(agenda.dataset.url, { method: 'POST', body });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok || !data.ok) throw new Error(data.erro || 'erro ao salvar');
        status.textContent = `Salvo ✓ · atualizada em ${data.updated}`;
      } catch (err) {
        days.forEach((iso) => dayBtn(iso)?.classList.toggle('busy', !busy)); // ...e desfaz se falhar
        status.textContent = `Não salvou (${err.message}). Confira a internet e tente de novo.`;
      }
    };
    editCal.addEventListener('click', (e) => {
      const b = e.target.closest('.cal-day');
      if (!b || b.disabled) return;
      const iso = b.dataset.day;
      if (!rangeBox.checked) { save([iso], !b.classList.contains('busy')); return; }
      if (!rangeStart) {
        rangeStart = iso;
        b.classList.add('pending');
        status.textContent = `Início: ${fmtDay(iso)}. Agora toque no último dia do período.`;
        return;
      }
      const [a, z] = rangeStart < iso ? [rangeStart, iso] : [iso, rangeStart];
      const busy = !dayBtn(rangeStart).classList.contains('busy'); // período segue o 1º dia: livre -> ocupa
      dayBtn(rangeStart).classList.remove('pending');
      rangeStart = null;
      save(daysBetween(a, z).filter((d) => dayBtn(d) && !dayBtn(d).disabled), busy);
    });
    rangeBox.addEventListener('change', () => {
      if (rangeStart) dayBtn(rangeStart)?.classList.remove('pending');
      rangeStart = null;
    });
  }

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
  // Mural de pescarias: reduz a foto antes de enviar (foto de celular tem 5-12 MB e a internet
  // de rancho costuma ser fraca)
  document.querySelectorAll('form[data-shrink]').forEach((form) => {
    form.addEventListener('submit', async (e) => {
      if (form.dataset.ready) return;
      e.preventDefault();
      const input = form.querySelector('input[type=file]');
      const btn = form.querySelector('button');
      btn.disabled = true;
      btn.textContent = 'Enviando…';
      if (input?.files[0] && window.DataTransfer) {
        const small = await shrink(input.files[0]);
        if (small !== input.files[0]) {
          const dt = new DataTransfer();
          dt.items.add(small);
          input.files = dt.files;
        }
      }
      form.dataset.ready = '1';
      form.submit();
    });
  });

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
