/* Quadro "Pesca hoje": melhores horários para pescar na represa, com a mesma nota do Nuvem
   (https://rlsdmm.github.io/nuvem/#pesca). Previsão do Open-Meteo, calculada no navegador.
   O quadro vem escondido do servidor e só aparece se a previsão chegar. */
(() => {
  const box = document.querySelector("[data-fishcast]");
  if (!box) return;
  const LAT = Number(box.dataset.lat), LON = Number(box.dataset.lon);
  const CACHE = "pesca-hoje:v1", VALIDADE = 30 * 60000;

  const round = (v) => { const r = Math.round(v); return Object.is(r, -0) ? 0 : r; };
  const hourOf = (t) => Number(t.slice(11, 13));
  const minutesOf = (t) => hourOf(t) * 60 + Number(t.slice(14, 16));
  const pad2 = (n) => String(n).padStart(2, "0");

  /* ---------- Lua (fórmulas de baixa precisão, iguais às do Nuvem) ---------- */
  const RAD = Math.PI / 180, OBLIQ = 23.4397 * RAD;
  const daysJ2000 = (ms) => ms / 86400000 + 2440587.5 - 2451545;
  function moonCoords(d) {
    const L = RAD * (218.316 + 13.176396 * d), M = RAD * (134.963 + 13.064993 * d), F = RAD * (93.272 + 13.22935 * d);
    const l = L + RAD * 6.289 * Math.sin(M), b = RAD * 5.128 * Math.sin(F);
    return {
      ra: Math.atan2(Math.sin(l) * Math.cos(OBLIQ) - Math.tan(b) * Math.sin(OBLIQ), Math.cos(l)),
      dec: Math.asin(Math.sin(b) * Math.cos(OBLIQ) + Math.cos(b) * Math.sin(OBLIQ) * Math.sin(l)),
    };
  }
  function moonAltitude(ms) {
    const d = daysJ2000(ms), { ra, dec } = moonCoords(d), phi = LAT * RAD;
    const H = RAD * (280.16 + 360.9856235 * d) + LON * RAD - ra;
    return Math.asin(Math.sin(phi) * Math.sin(dec) + Math.cos(phi) * Math.cos(dec) * Math.cos(H)) / RAD;
  }
  function moonPhase(ms) {
    const d = daysJ2000(ms), M = RAD * (357.5291 + .98560028 * d);
    const sun = M + RAD * (1.9148 * Math.sin(M) + .02 * Math.sin(2 * M)) + RAD * 102.9372 + Math.PI;
    const mm = RAD * (134.963 + 13.064993 * d);
    const moon = RAD * (218.316 + 13.176396 * d) + RAD * 6.289 * Math.sin(mm);
    return (((moon - sun) / (2 * Math.PI)) % 1 + 1) % 1;
  }
  function moonName(p) {
    if (p < .03 || p > .97) return "Lua nova";
    if (p < .22) return "Lua crescente";
    if (p < .28) return "Quarto crescente";
    if (p < .47) return "Crescente gibosa";
    if (p < .53) return "Lua cheia";
    if (p < .72) return "Minguante gibosa";
    if (p < .78) return "Quarto minguante";
    return "Lua minguante";
  }
  function localToMs(dateStr, minutes, offsetSec) {
    const [y, m, d] = dateStr.split("-").map(Number);
    return Date.UTC(y, m - 1, d) + minutes * 60000 - offsetSec * 1000;
  }
  function moonDay(dateStr, off) {
    const STEP = 5, HORIZON = .125, out = { rise: null, set: null, over: null, under: null };
    const alt = (min) => moonAltitude(localToMs(dateStr, min, off));
    let prev = alt(-STEP), cur = alt(0);
    for (let m = 0; m < 1440; m += STEP) {
      const next = alt(m + STEP);
      if (cur > prev && cur >= next && cur > 0) out.over = m;
      if (cur < prev && cur <= next && cur < 0) out.under = m;
      if (cur < HORIZON && next >= HORIZON) out.rise = m + STEP * (HORIZON - cur) / (next - cur);
      if (cur >= HORIZON && next < HORIZON) out.set = m + STEP * (cur - HORIZON) / (cur - next);
      prev = cur; cur = next;
    }
    return out;
  }

  /* ---------- Nota de pesca (mesmas regras e pesos do Nuvem) ---------- */
  const PESOS = { luz: 40, pressao: 15, vento: 15, chuva: 15, temp: 5, lua: 10 };
  function fishHour(x) {
    const pros = [], near = (a, b, r) => a != null && b != null && Math.abs(a - b) <= r, m = x.minute;
    let luz;
    if (near(m, x.rise, 90)) { luz = 1; pros.push("Amanhecer"); }
    else if (near(m, x.set, 90)) { luz = 1; pros.push("Entardecer"); }
    else if (near(m, x.rise, 150) || near(m, x.set, 150)) luz = .55;
    else if (x.rise != null && m > x.rise && m < x.set) luz = .3;
    else luz = .1;

    let pressao = .6;
    if (x.pressure24 != null) {
      const p = x.pressure24;
      if (p <= -1 && p >= -6) { pressao = 1; pros.push("Pressão caindo aos poucos"); }
      else if (p < -6) pressao = .4;
      else if (p < 1) { pressao = .75; pros.push("Pressão estável"); }
      else if (p <= 4) pressao = .5;
      else pressao = .25;
    }
    let vento;
    const w = x.wind;
    if (w < 3) vento = .7;
    else if (w <= 15) { vento = 1; pros.push("Vento fraco"); }
    else if (w <= 25) vento = .6;
    else if (w <= 35) vento = .3;
    else vento = .05;

    let chuva;
    if (x.rain > 4) chuva = .1;
    else if (x.rain > 1 || x.rainChance >= 70) chuva = .45;
    else if (x.rain > .2 || x.rainChance >= 40) chuva = .75;
    else { chuva = 1; pros.push("Sem chuva"); }

    const temp = x.temp >= 22 && x.temp <= 33 ? 1 : x.temp >= 17 && x.temp <= 36 ? .6 : .25;

    let lua = .4;
    if (near(m, x.moon.over, 60) || near(m, x.moon.under, 60)) { lua = 1; pros.push("Período forte da lua"); }
    else if (near(m, x.moon.rise, 30) || near(m, x.moon.set, 30)) { lua = .8; pros.push("Período secundário da lua"); }
    if (x.phase < .07 || x.phase > .93 || Math.abs(x.phase - .5) < .07) lua = Math.min(1, lua + .1);

    let score = luz * PESOS.luz + pressao * PESOS.pressao + vento * PESOS.vento + chuva * PESOS.chuva + temp * PESOS.temp + lua * PESOS.lua;
    let perigo = null;
    if (x.code >= 95) { score = Math.min(score, 10); perigo = "Risco de raios"; }
    else if (x.gust >= 45 || x.wind >= 30) { score = Math.min(score, 15); perigo = "Vento forte para barco"; }
    else if (x.code === 65 || x.code === 82) score = Math.min(score, 25);
    return { score: round(score), pros, perigo };
  }
  function band(s) {
    if (s >= 80) return ["Ótimo", "otimo"];
    if (s >= 65) return ["Bom", "bom"];
    if (s >= 45) return ["Regular", "regular"];
    return ["Ruim", "ruim"];
  }
  function topReasons(lista, limite) {
    const n = new Map();
    lista.flat().forEach((r) => n.set(r, (n.get(r) || 0) + 1));
    return [...n.entries()].sort((a, b) => b[1] - a[1]).slice(0, limite).map(([r]) => r);
  }
  function windows(horas) {
    const validas = horas.filter((x) => !x.past);
    const cands = [];
    for (let k = 0; k < validas.length; k++) {
      const a = validas[k], b = validas[k + 1];
      const par = b && b.hour === a.hour + 1 ? [a, b] : [a];
      cands.push({ start: a.hour, end: par[par.length - 1].hour + 1, completa: par.length === 2,
        score: round(par.reduce((s, x) => s + x.score, 0) / par.length), pros: topReasons(par.map((x) => x.pros), 3) });
    }
    const ordem = cands.filter((c) => c.completa || validas.length === 1).sort((p, q) => q.score - p.score);
    const melhor = ordem[0];
    if (!melhor) return [];
    const segunda = ordem.find((c) => Math.abs(c.start - melhor.start) >= 4 && c.score >= 40);
    return (segunda ? [melhor, segunda] : [melhor]).sort((p, q) => p.start - q.start);
  }
  function days(d) {
    const h = d.hourly, off = d.utc_offset_seconds, agora = d.current.time.slice(0, 13);
    return d.daily.time.map((dia, k) => {
      const rise = d.daily.sunrise[k] ? minutesOf(d.daily.sunrise[k]) : null;
      const set = d.daily.sunset[k] ? minutesOf(d.daily.sunset[k]) : null;
      const moon = moonDay(dia, off), phase = moonPhase(localToMs(dia, 720, off));
      const horas = [];
      h.time.forEach((t, j) => {
        if (t.slice(0, 10) !== dia) return;
        const before = j >= 24 ? h.pressure_msl[j - 24] : null;
        const base = { hour: hourOf(t), minute: hourOf(t) * 60 + 30, rise, set, moon, phase, code: h.weather_code[j],
          wind: h.wind_speed_10m[j] ?? 0, gust: h.wind_gusts_10m[j] ?? 0, rain: h.precipitation[j] ?? 0,
          rainChance: h.precipitation_probability[j] ?? 0, temp: h.temperature_2m[j],
          pressure24: before == null || h.pressure_msl[j] == null ? null : h.pressure_msl[j] - before, past: t.slice(0, 13) < agora };
        horas.push({ ...base, ...fishHour(base) });
      });
      // Horário colado a raio ou vento perigoso também não serve: dá pouco tempo para sair da água
      horas.forEach((x) => { if (!x.perigo && horas.some((y) => y.perigo && Math.abs(y.hour - x.hour) <= 2)) x.score = Math.min(x.score, 30); });
      const janelas = windows(horas), restantes = horas.filter((x) => !x.past);
      const claras = restantes.filter((x) => rise == null || (x.minute >= rise - 60 && x.minute <= set + 60));
      const amostra = claras.length ? claras : restantes;
      const media = amostra.length ? amostra.reduce((s, x) => s + x.score, 0) / amostra.length : 0;
      const alertas = [...new Set(restantes.map((x) => x.perigo).filter(Boolean))];
      const best = janelas.reduce((a, b) => (b.score > a.score ? b : a), janelas[0]);
      let score = best ? round(.7 * best.score + .3 * media) : null;
      if (score != null && alertas.length) score = Math.min(score, 60); // dia com alerta nunca aparece como bom
      return { dia, score, janelas, alertas, phase };
    });
  }

  /* ---------- Tela ---------- */
  const SEMANA = ["Dom", "Seg", "Ter", "Qua", "Qui", "Sex", "Sáb"];
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const dayLabel = (iso, k) => (k === 0 ? "Hoje" : k === 1 ? "Amanhã" : SEMANA[new Date(iso + "T12:00:00Z").getUTCDay()]);
  const janelaTxt = (j) => `${pad2(j.start)}h às ${pad2(j.end % 24)}h`;

  function render(d) {
    const lista = days(d).slice(0, 3);
    // Depois que acabam as boas horas de hoje (fim da noite), o quadro já mostra amanhã
    const k = lista[0].janelas.length && lista[0].score != null ? 0 : 1;
    const dia = lista[k];
    if (!dia || !dia.janelas.length) return;
    box.querySelector("[data-fc-title]").textContent = k === 0 ? "Pesca hoje" : "Pesca amanhã";
    box.querySelector("[data-fc-body]").innerHTML = `
      <ul class="fc-windows">${dia.janelas.map((j) => {
        const [nome, cls] = band(j.score);
        return `<li><strong class="fc-hour">${janelaTxt(j)}</strong>
          <span class="fc-score band-${cls}">${j.score} · ${nome}</span>
          ${j.pros.length ? `<span class="fc-why">${esc(j.pros.join(" · "))}</span>` : ""}</li>`;
      }).join("")}</ul>
      ${dia.alertas.length ? `<p class="fc-alert">⚠ ${esc(dia.alertas.join(" e "))} ${k === 0 ? "hoje" : "amanhã"}. Fique de olho no céu.</p>` : ""}
      <p class="fc-days">${lista.map((x, i) => x.score == null ? "" :
        `<span${i === k ? ' aria-current="date"' : ""}>${dayLabel(x.dia, i)} <b class="band-${band(x.score)[1]}">${x.score}</b></span>`).join("")}
        <span class="fc-moon">${moonName(dia.phase)}</span></p>`;
    box.hidden = false;
  }

  function cached() {
    try {
      const c = JSON.parse(sessionStorage.getItem(CACHE));
      return c && Date.now() - c.at < VALIDADE ? c.data : null;
    } catch { return null; }
  }
  async function load() {
    const hit = cached();
    if (hit) return hit;
    const u = new URL("https://api.open-meteo.com/v1/forecast");
    u.search = new URLSearchParams({ latitude: LAT, longitude: LON, current: "temperature_2m",
      hourly: "temperature_2m,precipitation_probability,precipitation,weather_code,pressure_msl,wind_speed_10m,wind_gusts_10m",
      daily: "sunrise,sunset", timezone: "America/Sao_Paulo", forecast_days: 3, past_hours: 24 });
    const ctl = new AbortController(), limite = setTimeout(() => ctl.abort(), 10000);
    try {
      const r = await fetch(u, { signal: ctl.signal });
      if (!r.ok) throw new Error("HTTP " + r.status);
      const data = await r.json();
      try { sessionStorage.setItem(CACHE, JSON.stringify({ at: Date.now(), data })); } catch { /* sem armazenamento */ }
      return data;
    } finally { clearTimeout(limite); }
  }
  load().then(render).catch(() => { /* sem previsão, o quadro continua escondido */ });
})();
