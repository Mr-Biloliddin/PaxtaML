/* Oq Oltin — клиент. Страницы: overview, field, phyto (демо-данные) и ai (реальная модель). */
"use strict";

const view = document.getElementById("view");
const fileInput = document.getElementById("fileInput");
const dropOverlay = document.getElementById("dropOverlay");

const state = {
  info: null,        // /api/info — модель, классы, метрики
  demo: null,        // /api/demo — демо-данные хозяйства + примеры фото
  history: [],       // /api/history — последние реальные анализы
  result: null,      // последний результат анализа
  busy: false,
  error: null,
  preview: null,     // objectURL загружаемого фото
};

/* ---------- helpers ---------- */
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const num = (v, d = 0) => Number(v).toLocaleString("ru-RU", { minimumFractionDigits: d, maximumFractionDigits: d });
const pct = (p, d = 1) => num(p * 100, d) + "%";
const icon = {
  upload: '<svg viewBox="0 0 24 24"><path d="M12 16V4M7 9l5-5 5 5M4 17v3h16v-3"/></svg>',
  cal: '<svg viewBox="0 0 24 24"><rect x="4" y="5" width="16" height="15" rx="2"/><path d="M4 10h16M9 3v4M15 3v4"/></svg>',
  check: '<svg viewBox="0 0 24 24"><path d="m5 12 5 5 9-10"/></svg>',
  leaf: '<svg viewBox="0 0 24 24"><path d="M5 19c0-8 5-14 15-15-1 10-7 15-15 15zM5 19l7-7"/></svg>',
};
const demoTag = '<span class="demo-tag" title="Страница заполнена демонстрационными данными">демо-данные</span>';

function sample(cls, i = 0) {
  const list = state.demo?.samples?.[cls] || [];
  return list.length ? list[i % list.length] : null;
}
function imgTag(src, cls = "", alt = "") {
  return src ? `<img class="${cls}" src="${esc(src)}" alt="${esc(alt)}" loading="lazy">` : `<span class="${cls}"></span>`;
}
function titleOf(cls) { return state.info?.titles?.[cls] || cls; }
function timeAgo(iso) {
  const d = new Date(iso), s = (Date.now() - d) / 1000;
  if (s < 60) return "только что";
  if (s < 3600) return `${Math.floor(s / 60)} мин назад`;
  if (s < 86400) return `${Math.floor(s / 3600)} ч назад`;
  return d.toLocaleDateString("ru-RU", { day: "numeric", month: "short" }) + " · " + d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
}

async function api(path, opts) {
  const r = await fetch(path, opts);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || `Ошибка сервера (${r.status})`);
  return data;
}

/* ---------- line chart (SVG) ---------- */
function lineChart({ w = 680, h = 230, xs, series, yMin = 0, yMax, yTicks, xLabel, forecastFrom, marker }) {
  const pad = { l: 36, r: 12, t: 12, b: 26 };
  const iw = w - pad.l - pad.r, ih = h - pad.t - pad.b;
  const x0 = xs[0], x1 = xs[xs.length - 1];
  const X = x => pad.l + ((x - x0) / (x1 - x0 || 1)) * iw;
  const Y = y => pad.t + ih - ((y - yMin) / (yMax - yMin)) * ih;
  let out = `<svg class="chart" viewBox="0 0 ${w} ${h}" role="img">`;
  if (forecastFrom != null) {
    out += `<rect x="${X(forecastFrom)}" y="${pad.t}" width="${X(x1) - X(forecastFrom)}" height="${ih}" fill="#f6f1e5"/>`;
    out += `<text x="${X(forecastFrom) + 8}" y="${pad.t + 14}">прогноз</text>`;
  }
  for (const t of yTicks) {
    out += `<line x1="${pad.l}" x2="${w - pad.r}" y1="${Y(t)}" y2="${Y(t)}" stroke="#ece7dc"/>`;
    out += `<text x="${pad.l - 8}" y="${Y(t) + 4}" text-anchor="end">${t}</text>`;
  }
  xs.forEach((x, i) => {
    const lab = xLabel(x, i);
    if (lab) out += `<text x="${X(x)}" y="${h - 6}" text-anchor="middle">${lab}</text>`;
  });
  for (const s of series) {
    // null в values = точки нет (например, прогноз начинается с текущей недели)
    const pts = s.values.map((v, i) => (v == null ? null : [X(xs[i]), Y(v)])).filter(Boolean);
    if (!pts.length) continue;
    const d = pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" ");
    if (s.area) out += `<path d="${d} L${pts.at(-1)[0]} ${Y(yMin)} L${pts[0][0]} ${Y(yMin)} Z" fill="${s.area}"/>`;
    out += `<path d="${d}" fill="none" stroke="${s.color}" stroke-width="${s.width || 2.5}" ${s.dash ? `stroke-dasharray="${s.dash}"` : ""} stroke-linejoin="round" stroke-linecap="round"/>`;
  }
  if (marker) {
    const mx = X(marker.x), my = Y(marker.y);
    out += `<circle cx="${mx}" cy="${my}" r="6" fill="#fff" stroke="#1d3d2a" stroke-width="3"/>`;
    const bw = marker.label.length * 8 + 22;
    out += `<rect x="${mx - bw - 8}" y="${my - 44}" width="${bw}" height="28" rx="6" fill="#17231b"/>`;
    out += `<text x="${mx - bw / 2 - 8}" y="${my - 25}" text-anchor="middle" style="fill:#fff;font-size:12.5px">${esc(marker.label)}</text>`;
  }
  return out + "</svg>";
}

/* ---------- pages ---------- */
function pageOverview() {
  const d = state.demo, k = d.kpi, hc = d.height_chart;
  const cur = hc.current_week, lastFact = hc.fact.at(-1);
  // прогноз: от текущего факта вдоль нормы сорта
  const forecast = hc.norm.map((v, i) => (hc.weeks[i] < cur ? null : hc.weeks[i] === cur ? lastFact : v));
  const f7 = d.fields[0];
  const statusLabel = { ok: "Норма", disease: "Болезнь", water: "Нужен полив", watch: "Наблюдение" };
  return `
  <section class="page">
    <div class="page-head">
      <div>
        <div class="eyebrow">Сезон ${d.season.year} · ${d.season.day}-й день вегетации ${demoTag}</div>
        <h1>Мониторинг роста хлопка</h1>
      </div>
      <div class="head-actions">
        <span class="btn">${icon.cal}${esc(d.season.date)}</span>
        <a class="btn primary" href="#/ai">${icon.leaf}Анализ по фото</a>
      </div>
    </div>

    <div class="grid kpis">
      <div class="card kpi"><div class="label">Площадь под хлопком</div><div class="value">${num(k.area_ha)}<small>га</small></div><div class="sub">${k.fields} полей · ${k.varieties} сорта</div></div>
      <div class="card kpi"><div class="label">Средняя высота растений</div><div class="value">${k.height_cm}<small>см</small></div><div class="sub up">▲ +${num(k.height_week_delta, 1)} см за неделю</div></div>
      <div class="card kpi"><div class="label">Индекс вегетации NDVI</div><div class="value">${num(k.ndvi, 2)}</div><div class="meter"><i style="width:${k.ndvi * 100}%"></i></div></div>
      <div class="card kpi dark"><div class="label">Прогноз урожайности</div><div class="value">${num(k.yield_forecast, 1)}<small>ц/га</small></div><div class="sub">+${num(k.yield_vs_plan, 1)} ц/га к плану сезона</div></div>
    </div>

    <div class="grid two">
      <div class="card">
        <div class="card-head"><h2>Динамика высоты растений, см</h2>
          <div class="legend"><span><i></i>Факт</span><span><i class="dash"></i>Норма сорта</span></div></div>
        ${lineChart({
          xs: hc.weeks, yMax: 100, yTicks: [0, 25, 50, 75, 100], forecastFrom: cur,
          xLabel: (x, i) => (i === 0 ? "нед 1" : [4, 7, 9, 11].includes(x) ? x : ""),
          series: [
            { values: hc.norm.slice(0, hc.fact.length), color: "#b9612a", dash: "5 5", width: 2 },
            { values: forecast, color: "#b9612a", dash: "5 5", width: 2 },
            { values: hc.fact, color: "#1d3d2a", area: "rgba(29,61,42,.07)", width: 3 },
          ],
          marker: { x: cur, y: lastFact, label: `${lastFact} см` },
        })}
      </div>
      <div class="photo">
        ${imgTag(sample(f7.sample, 1), "", "Фото поля")}
        ${sample(f7.sample, 1) ? "" : '<div class="noimg">Фото появится после split_dataset.py</div>'}
        <div class="tag"><span class="pill">Фото с дрона · 09:40</span></div>
        <div class="overlay">
          <div class="row"><b>Поле №${f7.id} «${esc(f7.name)}»</b><span class="pill yellow">${esc(f7.phase)}</span></div>
          <small>Сорт «${esc(f7.variety)}» · ${f7.ha} га · высота ${f7.height} см · NDVI ${num(f7.ndvi, 2)}</small>
        </div>
      </div>
    </div>

    <div class="grid two">
      <div class="card">
        <div class="card-head"><h2>Состояние полей</h2><a class="link" href="#/field">Все ${k.fields} полей →</a></div>
        <div class="table-wrap"><table>
          <thead><tr><th>Поле</th><th>Сорт</th><th>Фаза</th><th>Высота</th><th>NDVI</th><th>Статус</th></tr></thead>
          <tbody>${d.fields.slice(0, 4).map((f, i) => `
            <tr><td><div class="fieldname">${imgTag(sample(f.sample, i), "thumb")}<span>Поле №${f.id} «${esc(f.name)}»</span></div></td>
            <td>${esc(f.variety)}</td><td>${esc(f.phase)}</td><td class="mono">${f.height} см</td><td class="mono">${num(f.ndvi, 2)}</td>
            <td><span class="status st-${f.status}">${statusLabel[f.status]}</span></td></tr>`).join("")}
          </tbody></table></div>
      </div>
      <div style="display:flex;flex-direction:column;gap:20px">
        <div class="card">
          <div class="card-head"><h2>Уведомления</h2></div>
          <ul class="alerts">${d.alerts.map(a => `<li><span class="dot ${a.level}"></span><span>${a.field ? `<b>${esc(a.field)}:</b> ` : ""}${esc(a.text)}</span></li>`).join("")}</ul>
        </div>
        <div class="card weather">
          <div><div class="label" style="color:var(--muted);font-size:13.5px">${esc(d.weather.place)}, сегодня</div><div class="t">+${d.weather.temp} °C</div></div>
          <div class="r">Влажность воздуха ${d.weather.humidity}%<br>Ветер ${esc(d.weather.wind)}<br>Сумма эфф. t° ${num(d.weather.gdd)}</div>
        </div>
      </div>
    </div>
  </section>`;
}

function pageField() {
  const f = state.demo.field_detail;
  return `
  <section class="page">
    <div class="page-head">
      <div>
        <div class="crumbs"><a href="#/overview">Обзор</a> / Поля / №${f.id} ${demoTag}</div>
        <h1>Поле №${f.id} «${esc(f.name)}»</h1>
        <div class="chips"><span class="chip">Сорт «${esc(f.variety)}»</span><span class="chip">${f.ha} га</span><span class="chip">Посев ${esc(f.sown)}</span><span class="chip">Схема ${esc(f.scheme)}</span></div>
      </div>
      <div class="head-actions">
        <a class="btn primary" href="#/ai">${icon.upload}Добавить замер по фото</a>
      </div>
    </div>

    <div class="grid two-eq">
      <div class="photo" style="min-height:360px">
        ${imgTag(sample("Healthy Leaf", 0), "", "Контрольная точка")}
        <div class="tag"><span class="pill">Контрольная точка ${esc(f.point)}</span><span class="pill yellow">Цветение · 62%</span></div>
        <div class="overlay"><div class="stats3">
          <div><small>Высота</small><b>${f.height} см</b></div>
          <div><small>Густота</small><b>${esc(f.density)}</b></div>
          <div><small>Снимок</small><b>${esc(f.shot)}</b></div>
        </div></div>
      </div>
      <div class="card">
        <div class="card-head"><h2>Фазы развития</h2><span class="aside">${f.days} дня от посева</span></div>
        <div class="phases">${f.phases.map(p => `
          <div class="phase ${p.done >= 1 ? "done" : ""} ${p.current ? "current" : ""}">
            <div class="ic">${p.done >= 1 ? icon.check : ""}</div>
            <div><div class="top">${esc(p.name)}<span>${esc(p.date)}</span></div><div class="bar"><i style="width:${p.done * 100}%"></i></div></div>
          </div>`).join("")}
        </div>
      </div>
    </div>

    <div class="grid two-eq">
      <div class="grid metrics">
        ${f.metrics.map(m => `<div class="card metric"><div class="label" style="font-size:13.5px;color:var(--muted)">${esc(m.label)}</div><div class="value">${esc(m.value)}</div><div class="note tone-${m.tone}">${esc(m.note)}</div></div>`).join("")}
        <div class="card metric dark"><div class="label" style="font-size:13.5px;color:#c8d6c9">Прогноз сбора</div><div class="value">${esc(f.yield.value)}</div><div class="note" style="font-weight:400;color:#c8d6c9">${esc(f.yield.note)}</div></div>
      </div>
      <div class="card">
        <div class="card-head"><h2>Фотодневник</h2><a class="link" href="#/ai">+ Фото</a></div>
        <div class="diary">${f.diary.map((x, i) => `
          <figure><div class="im">${imgTag(sample("Healthy Leaf", i + 1))}</div><figcaption>${esc(x.date)} · ${esc(x.height)}</figcaption></figure>`).join("")}
        </div>
      </div>
    </div>
  </section>`;
}

function accRange(epochs) {
  // шкала от ближайшего круглого значения ниже минимума — чтобы рост точности был виден
  const lo = Math.min(...epochs.flatMap(e => [e.val_acc, e.val_f1]));
  const yMin = Math.max(0, Math.floor(lo * 10) / 10);
  const mid = Math.round(((yMin + 1) / 2) * 100) / 100;
  return { yMin, yMax: 1, yTicks: [yMin, mid, 1] };
}

function modelAccuracy() {
  const t = state.info?.test;
  if (t) return { value: pct(t.accuracy, 0), note: `на test, ${t.test_size} фото` };
  if (state.info?.val_f1) return { value: pct(state.info.val_f1, 0), note: "macro-F1 на val" };
  return { value: "—", note: "модель не загружена" };
}

function recentGrid(items, empty) {
  if (!items.length) return `<div class="empty">${empty}</div>`;
  return `<div class="recent">${items.map(h => `
    <figure><div class="im"><img src="${esc(h.image)}" alt="" loading="lazy">
      <span class="pct ${h.severity === "ok" ? "ok" : h.severity === "warn" ? "warn" : ""}">${Math.round(h.confidence * 100)}%</span></div>
      <figcaption>${esc(titleOf(h.prediction))}<small>${h.field ? esc(h.field) + " · " : ""}${timeAgo(h.time)}</small></figcaption></figure>`).join("")}</div>`;
}

function pagePhyto() {
  const p = state.demo.phyto, acc = modelAccuracy();
  const lvl = { high: ["Высокий", "st-critical", "#b9612a"], mid: ["Средний", "st-mid", "#e0a36f"], ok: ["Норма", "st-ok", "#2f6b45"] };
  return `
  <section class="page">
    <div class="page-head">
      <div>
        <div class="eyebrow">Распознавание по фото листа ${demoTag}</div>
        <h1>Фитосанитарный контроль</h1>
      </div>
      <div class="head-actions"><a class="btn primary" href="#/ai">${icon.upload}Проверить лист</a></div>
    </div>

    <div class="grid kpis">
      <div class="card kpi"><div class="label">Проверено фото за неделю</div><div class="value">${num(p.checked_week)}</div></div>
      <div class="card kpi"><div class="label">Здоровые растения</div><div class="value">${num(p.healthy_pct, 1)}%</div></div>
      <div class="card kpi warn"><div class="label">Активные очаги</div><div class="value">${p.foci}</div></div>
      <div class="card kpi"><div class="label">Точность модели</div><div class="value">${acc.value}</div><div class="sub">${esc(acc.note)} · реальная</div></div>
    </div>

    <div class="grid two">
      <div class="cases">${p.cases.map((c, i) => {
        const [lab, cls, color] = lvl[c.level];
        return `<div class="card case">
          <div class="im">${imgTag(sample(c.class, i))}</div>
          <div>
            <h3><span>${esc(titleOf(c.class))}</span><span class="status ${cls}">${lab}</span></h3>
            <div class="meta">${esc(c.field)} · ${esc(c.area)} · ${c.shots} снимков</div>
            <div class="confrow"><span class="meta">Уверенность модели</span><span class="track"><i style="width:${c.confidence * 100}%;background:${color}"></i></span><b>${Math.round(c.confidence * 100)}%</b></div>
            <p>${esc(c.text)}</p>
          </div></div>`;
      }).join("")}
      </div>
      <div class="card">
        <div class="card-head"><h2>Карта риска по полям</h2></div>
        <div class="riskmap">${Object.entries(state.demo.risk_map).map(([n, r]) => `<div class="rk-${r}">${n}</div>`).join("")}</div>
        <div class="rk-legend"><span><i class="rk-low"></i>Низкий</span><span><i class="rk-mid"></i>Средний</span><span><i class="rk-high"></i>Высокий</span></div>
        <div class="sep"></div>
        <h2 style="font-size:15px;margin-bottom:12px">Факторы риска на неделю</h2>
        <div class="factors">${p.factors.map(f => `<div><span>${esc(f.name)}</span><b class="${f.level === "низкий" ? "lvl-lo" : "lvl-hi"}">${esc(f.level)}</b></div>`).join("")}</div>
        <div class="sep"></div>
        <div class="note-box">${esc(p.traps)}</div>
      </div>
    </div>

    <div class="card">
      <div class="card-head"><h2>Последние распознавания</h2><span class="aside">реальные анализы с этого компьютера</span></div>
      ${recentGrid(state.history.slice(0, 8), 'Пока пусто — загрузите фото на странице <a class="link" href="#/ai">ИИ-анализ</a>.')}
    </div>
  </section>`;
}

function pageAI() {
  const info = state.info, r = state.result;
  const ok = !!info;
  const sevOf = r ? r.advice.severity : "ok";
  const t = r?.timing_ms;
  const steps = [
    ["Загрузка и декодирование снимка", t?.load],
    [`Предобработка (${info?.image_size || 224}×${info?.image_size || 224}, нормализация)`, t?.preprocess],
    [`Классификация болезни (CNN · ${esc(info?.model?.split(".")[0] || "—")})`, t?.inference],
    ["Рекомендация агроному", t?.advice],
  ];
  const tr = info?.training, test = info?.test;
  const bestEpoch = tr?.epochs?.length ? tr.epochs.reduce((a, b) => (b.val_f1 > a.val_f1 ? b : a)) : null;
  const nums = test
    ? [["Accuracy", test.accuracy], ["Precision", test.precision], ["Recall", test.recall], ["F1-score", test.f1]]
    : bestEpoch ? [["Accuracy (val)", bestEpoch.val_acc], ["F1 (val)", bestEpoch.val_f1]] : [];

  let viewer;
  if (state.preview || r) {
    viewer = `<img src="${esc(state.preview || r.image)}" alt="Загруженный снимок">
      <div class="cap">${r ? `Снимок · ${new Date().toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })}` : "Снимок загружен"}</div>
      <div class="status-bar">
        <div class="row"><span>${state.busy ? "Анализ…" : state.error ? `<span class="err">${esc(state.error)}</span>` : "Анализ завершён"}</span>
          <b>${r && !state.busy ? Math.round(Object.values(r.timing_ms).reduce((a, b) => a + b, 0)) + " мс" : ""}</b></div>
        <div class="progress ${state.busy ? "run" : ""}"><i></i></div>
      </div>`;
  } else {
    viewer = `<div class="ph">${icon.upload}<b>Перетащите фото листа сюда</b><small>или нажмите, чтобы выбрать · можно вставить Ctrl+V · с телефона — камера</small></div>`;
  }

  return `
  <section class="page">
    <div class="page-head">
      <div>
        <div class="eyebrow">Нейросеть анализирует фото листьев хлопка</div>
        <h1>ИИ-анализ посевов</h1>
      </div>
      <div class="head-actions">
        <span class="model-pill ${ok ? "" : "off"}"><i></i><b>${ok ? "CottonNet" : "Модель"}</b>${ok ? ` · ${esc(info.device.toUpperCase())} · модель работает` : " · не подключена"}</span>
        <button class="btn primary" data-action="upload">${icon.upload}Загрузить снимок</button>
      </div>
    </div>

    <div class="grid ai-top">
      <div class="viewer" data-action="upload">${viewer}</div>
      <div class="ai-right">
        <div class="card diag">
          ${r ? `
            <div class="head">
              <div><div class="label">Диагноз модели</div><div class="name">${esc(r.advice.title)}</div></div>
              <div class="conf"><b class="sev-${sevOf}">${pct(r.confidence)}</b><small>уверенность</small></div>
            </div>
            ${r.low_confidence ? `<div class="lowconf">Низкая уверенность — сделайте ещё фото и проверьте растение вручную</div>` : ""}
            <div class="probs">${r.probabilities.map((p, i) => `
              <div class="prob ${i === 0 ? "top" : ""} ${i === 0 && sevOf === "ok" ? "ok" : ""}"><span>${esc(p.title)}</span><span class="track"><i style="width:${(p.p * 100).toFixed(1)}%"></i></span><b>${pct(p.p)}</b></div>`).join("")}
            </div>` : `
            <div class="label" style="color:var(--muted);font-size:13.5px">Диагноз модели</div>
            <div class="name" style="font-family:var(--display);font-size:20px;margin:6px 0 14px">Ожидает снимок</div>
            <div class="probs">${(info?.classes || []).map(c => `<div class="prob"><span>${esc(titleOf(c))}</span><span class="track"><i style="width:0"></i></span><b>—</b></div>`).join("")}</div>`}
        </div>
      </div>
    </div>

    <div class="grid ai-mid">
      <div class="card">
        <div class="card-head"><h2>Как работает модель</h2><span class="aside">${r ? "время этого анализа" : ""}</span></div>
        <ol class="steps">${steps.map(([name, ms], i) => `<li><span class="n">${i + 1}</span><span>${name}</span><b>${ms != null ? num(ms, ms < 10 ? 1 : 0) + " мс" : "—"}</b></li>`).join("")}</ol>
      </div>
      <div class="card dark reco">
        <h2>${r ? "Что проверить / сделать" : "Рекомендация агроному"}</h2>
        ${r ? `<div class="cause">${esc(r.advice.cause)}</div><ul>${r.advice.actions.map(a => `<li>${esc(a)}</li>`).join("")}</ul>
          <div class="fine">Результат по фото — сигнал для осмотра, а не окончательный диагноз.</div>`
          : `<div class="cause">После анализа здесь появится вероятная причина и конкретные шаги для агронома.</div>`}
      </div>
    </div>

    <div class="grid ai-mid">
      <div class="card quality">
        <div class="card-head"><h2>Качество модели</h2><span class="aside">${tr ? `обучена на ${num(tr.train_size)} снимках · ${tr.classes.length} классов` : ""}</span></div>
        ${nums.length ? `<div class="nums">${nums.map(([k, v]) => `<div><small>${k}</small><b>${pct(v, 1)}</b></div>`).join("")}</div>` : `<div class="empty">Метрики появятся после обучения.</div>`}
        ${test ? "" : `<div class="cap" style="margin-bottom:10px">Для метрик на отложенной выборке запустите <code>python src/evaluate.py --weights …/best.pt</code></div>`}
        ${tr?.epochs?.length > 1 ? `<div class="cap">Точность по эпохам (1–${tr.epochs.length}): accuracy на val — сплошная, macro-F1 — пунктир</div>` +
          lineChart({
            w: 680, h: 170, xs: tr.epochs.map(e => e.epoch), ...accRange(tr.epochs),
            xLabel: (x, i) => (i === 0 || i === tr.epochs.length - 1 || x % 5 === 0 ? x : ""),
            series: [
              { values: tr.epochs.map(e => e.val_f1), color: "#b9612a", dash: "5 5", width: 2 },
              { values: tr.epochs.map(e => e.val_acc), color: "#1d3d2a", width: 2.5 },
            ],
          }) : ""}
      </div>
      <div class="card">
        <div class="card-head"><h2>Последние распознавания</h2><span class="aside">всего: ${state.history.length}</span></div>
        ${recentGrid(state.history.slice(0, 4), "Здесь появятся ваши анализы.")}
      </div>
    </div>
  </section>`;
}

/* ---------- router ---------- */
const pages = { overview: pageOverview, field: pageField, phyto: pagePhyto, ai: pageAI };

function render() {
  const name = (location.hash.replace("#/", "") || "overview").split("?")[0];
  const page = pages[name] ? name : "overview";
  document.querySelectorAll("#nav a").forEach(a => a.classList.toggle("active", a.dataset.page === page));
  if (page !== "ai" && !state.demo) { view.innerHTML = '<div class="page"><div class="empty">Загрузка…</div></div>'; return; }
  try {
    view.innerHTML = pages[page]();
  } catch (e) {
    console.error(e);
    view.innerHTML = `<div class="page"><div class="card err">Ошибка отображения: ${esc(e.message)}</div></div>`;
  }
}

/* ---------- analysis ---------- */
async function analyze(file) {
  if (!file || !file.type.startsWith("image/")) return;
  if (location.hash !== "#/ai") location.hash = "#/ai";
  if (state.preview) URL.revokeObjectURL(state.preview);
  state.preview = URL.createObjectURL(file);
  state.busy = true; state.error = null; state.result = null;
  render();
  const fd = new FormData();
  fd.append("file", file);
  try {
    state.result = await api("/api/predict", { method: "POST", body: fd });
    state.history = await api("/api/history?limit=24");
  } catch (e) {
    state.error = e.message;
  } finally {
    state.busy = false;
    render();
  }
}

document.addEventListener("click", e => {
  if (e.target.closest("[data-action=upload]") && !state.busy) fileInput.click();
});
fileInput.addEventListener("change", () => { analyze(fileInput.files[0]); fileInput.value = ""; });

let dragDepth = 0;
window.addEventListener("dragenter", e => { if (e.dataTransfer?.types?.includes("Files")) { dragDepth++; dropOverlay.classList.add("show"); } });
window.addEventListener("dragleave", () => { if (--dragDepth <= 0) { dragDepth = 0; dropOverlay.classList.remove("show"); } });
window.addEventListener("dragover", e => e.preventDefault());
window.addEventListener("drop", e => {
  e.preventDefault(); dragDepth = 0; dropOverlay.classList.remove("show");
  analyze(e.dataTransfer.files[0]);
});
window.addEventListener("paste", e => { const f = [...(e.clipboardData?.files || [])][0]; if (f) analyze(f); });
window.addEventListener("hashchange", () => { render(); view.focus({ preventScroll: true }); window.scrollTo(0, 0); });

/* ---------- boot ---------- */
(async function boot() {
  render();
  const [info, demo, history] = await Promise.allSettled([api("/api/info"), api("/api/demo"), api("/api/history?limit=24")]);
  if (info.status === "fulfilled") state.info = info.value;
  if (demo.status === "fulfilled") state.demo = demo.value;
  if (history.status === "fulfilled") state.history = history.value;
  if (state.demo) {
    const farm = document.getElementById("farm");
    farm.querySelector("b").textContent = state.demo.farm.name;
    farm.querySelector("span").textContent = state.demo.farm.region;
    document.getElementById("fociBadge").textContent = state.demo.phyto.foci;
  }
  render();
})();
