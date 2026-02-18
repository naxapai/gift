const kpiGrid = document.getElementById("kpiGrid");
const giftSelect = document.getElementById("giftSelect");
const lineChart = document.getElementById("lineChart");
const screenerBody = document.getElementById("screenerBody");
const signalsList = document.getElementById("signalsList");
const favoritesList = document.getElementById("favoritesList");
const refreshBtn = document.getElementById("refreshBtn");
const liveStatus = document.getElementById("liveStatus");
const giftModal = document.getElementById("giftModal");
const giftModalBody = document.getElementById("giftModalBody");
const giftModalTitle = document.getElementById("giftModalTitle");
const giftModalClose = document.getElementById("giftModalClose");
const pageSizeSelect = document.getElementById("pageSizeSelect");
const prevPageBtn = document.getElementById("prevPageBtn");
const nextPageBtn = document.getElementById("nextPageBtn");
const pageInfo = document.getElementById("pageInfo");

const signalFilter = document.getElementById("signalFilter");
const marketFilter = document.getElementById("marketFilter");
const collectionFilter = document.getElementById("collectionFilter");
const modelFilter = document.getElementById("modelFilter");
const backdropFilter = document.getElementById("backdropFilter");
const symbolFilter = document.getElementById("symbolFilter");
const sortBy = document.getElementById("sortBy");
const order = document.getElementById("order");
const giftSearch = document.getElementById("giftSearch");
const favoritesOnly = document.getElementById("favoritesOnly");

let marketRows = [];
let currentGiftId = "";
let autoRefreshTimer = null;
let favorites = new Set();
let lastSummary = null;
let currentPage = 1;
let pageSize = 25;

function loadFavorites() {
  return fetchJson("/api/user/favorites")
    .then((resp) => {
      const ids = resp?.data?.gift_ids;
      favorites = new Set(Array.isArray(ids) ? ids : []);
    })
    .catch(() => {
      favorites = new Set();
    });
}

function isFavorite(giftId) {
  return favorites.has(giftId);
}

async function toggleFavorite(giftId) {
  const resp = await fetchJson("/api/user/favorites/toggle", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ gift_id: giftId }),
  });
  const ids = resp?.data?.gift_ids;
  favorites = new Set(Array.isArray(ids) ? ids : []);
}

function getGiftIcon(giftId = "") {
  const icons = ["🎁", "🌹", "🌷", "💎", "⭐", "🎈", "👑", "🧧", "🎀", "✨"];
  let hash = 0;
  for (let i = 0; i < giftId.length; i++) hash = (hash + giftId.charCodeAt(i) * (i + 1)) % 9973;
  return icons[hash % icons.length];
}

function clsForValue(v) {
  if (v > 0) return "pos";
  if (v < 0) return "neg";
  return "";
}

function formatPct(v) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return "—";
  const sign = v > 0 ? "+" : "";
  return `${sign}${Number(v).toFixed(2)}%`;
}

function formatPrice(v) {
  return Number(v).toFixed(2);
}

function formatTon(v, maxDecimals = 4) {
  const n = Number(v);
  if (!Number.isFinite(n)) return "-";
  return n.toFixed(maxDecimals).replace(/\.?0+$/, "");
}

function withShare(label, share) {
  return share ? `${label} (${share})` : label;
}

function getMultiSelectedValues(selectEl) {
  return Array.from(selectEl.selectedOptions || [])
    .map((o) => (o.value || "").trim())
    .filter(Boolean);
}

function restoreMultiSelection(selectEl, values) {
  const wanted = new Set(values || []);
  Array.from(selectEl.options || []).forEach((opt) => {
    opt.selected = wanted.has(opt.value);
  });
}

function bindMultiToggle(selectEl) {
  if (!selectEl) return;
  selectEl.addEventListener("mousedown", (e) => {
    const opt = e.target;
    if (!(opt instanceof HTMLOptionElement)) return;
    e.preventDefault();
    opt.selected = !opt.selected;
    selectEl.dispatchEvent(new Event("change", { bubbles: true }));
  });
}

function normalizeText(v) {
  return String(v || "")
    .toLowerCase()
    .replace(/[^a-z0-9а-яё]+/gi, "");
}

function renderGiftNameCell(r) {
  return `<a href="#" class="gift-link" data-gift-id="${r.gift_id}">${getGiftIcon(r.gift_id)} ${r.name}</a>`;
}

function renderFavoriteButton(giftId) {
  const active = isFavorite(giftId);
  return `<button class="fav-btn ${active ? "active" : ""}" data-fav-id="${giftId}" title="${active ? "Убрать из избранного" : "В избранное"}">${active ? "★" : "☆"}</button>`;
}

function renderKpi(data) {
  if (!kpiGrid) return;
  const items = [
    ["Состояние рынка", data.market_state],
    ["Всего подарков", String(data.rows.length)],
    ["В избранном", String(favorites.size)],
    ["Средний рост 7д", formatPct(data.avg_change_7d)],
    ["Средний рост 30д", formatPct(data.avg_change_30d)],
    ["BUY сигналы", String(data.buy_signals)],
    ["SELL сигналы", String(data.sell_signals)],
    ["Аномалии", String(data.anomalies)],
  ];

  kpiGrid.innerHTML = items
    .map(([label, value]) => {
      const valNum = Number.parseFloat(value);
      const cl = Number.isNaN(valNum) ? "" : clsForValue(valNum);
      return `<div class="kpi"><div class="label">${label}</div><div class="value ${cl}">${value}</div></div>`;
    })
    .join("");
}

function normalizeSummary(data) {
  const rows = Array.isArray(data?.rows) ? data.rows : [];
  return {
    market_state: data?.market_state || "—",
    avg_change_7d: Number.isFinite(data?.avg_change_7d) ? data.avg_change_7d : 0,
    avg_change_30d: Number.isFinite(data?.avg_change_30d) ? data.avg_change_30d : 0,
    buy_signals: Number.isFinite(data?.buy_signals) ? data.buy_signals : 0,
    sell_signals: Number.isFinite(data?.sell_signals) ? data.sell_signals : 0,
    anomalies: Number.isFinite(data?.anomalies) ? data.anomalies : 0,
    rows,
  };
}

function renderGiftOptions(rows) {
  const selectedBefore = currentGiftId || giftSelect.value;
  giftSelect.innerHTML = rows
    .map((r) => `<option value="${r.gift_id}">${getGiftIcon(r.gift_id)} ${r.name}</option>`)
    .join("");
  const hasSelected = rows.some((r) => r.gift_id === selectedBefore);
  currentGiftId = hasSelected && selectedBefore ? selectedBefore : rows[0]?.gift_id || "";
  giftSelect.value = currentGiftId;
}

function renderCollectionOptions(rows) {
  const selectedBefore = collectionFilter.value || "";
  const collections = [...new Set(rows.map((r) => r.collection || ""))]
    .filter(Boolean)
    .sort((a, b) => a.localeCompare(b));
  const options = ['<option value="">Все коллекции</option>']
    .concat(collections.map((c) => `<option value="${c}">${c}</option>`))
    .join("");
  collectionFilter.innerHTML = options;
  if (collections.includes(selectedBefore)) collectionFilter.value = selectedBefore;
}

function renderModelOptions(rows) {
  const selectedBefore = getMultiSelectedValues(modelFilter);
  const selectedCollection = (collectionFilter.value || "").trim().toLowerCase();
  const baseRows = selectedCollection
    ? rows.filter((r) => String(r.collection || "").trim().toLowerCase() === selectedCollection)
    : rows;
  const models = [...new Set(baseRows.map((r) => r.model || ""))]
    .filter(Boolean)
    .sort((a, b) => a.localeCompare(b));
  const options = ['<option value="">Все модели</option>']
    .concat(models.map((m) => `<option value="${m}">${m}</option>`))
    .join("");
  modelFilter.innerHTML = options;
  restoreMultiSelection(modelFilter, selectedBefore.filter((v) => models.includes(v)));
  if (!selectedBefore.length) modelFilter.selectedIndex = -1;
}

function renderBackdropOptions(options = []) {
  const selectedBefore = getMultiSelectedValues(backdropFilter);
  const values = (options || []).map((o) => o.value).filter(Boolean);
  const html = (options || []).map((o) => `<option value="${o.value}">${o.value}${o.count ? ` (${o.count})` : ""}</option>`)
    .join("");
  backdropFilter.innerHTML = html;
  restoreMultiSelection(backdropFilter, selectedBefore.filter((v) => values.includes(v)));
  if (!selectedBefore.length) backdropFilter.selectedIndex = -1;
}

function renderSymbolOptions(options = []) {
  const selectedBefore = getMultiSelectedValues(symbolFilter);
  const values = (options || []).map((o) => o.value).filter(Boolean);
  const html = (options || []).map((o) => `<option value="${o.value}">${o.value}${o.count ? ` (${o.count})` : ""}</option>`)
    .join("");
  symbolFilter.innerHTML = html;
  restoreMultiSelection(symbolFilter, selectedBefore.filter((v) => values.includes(v)));
  if (!selectedBefore.length) symbolFilter.selectedIndex = -1;
}

async function loadFilterOptions() {
  const resp = await fetchJson("/api/market/filters");
  const f = resp.data || {};
  const selectedCollection = collectionFilter.value || "";
  const selectedModels = getMultiSelectedValues(modelFilter);

  const collections = (f.collections || []).map((c) => c.slug || c.name).filter(Boolean);
  collectionFilter.innerHTML =
    ['<option value="">Все коллекции</option>']
      .concat(collections.map((c) => `<option value="${c}">${c}</option>`))
      .join("");
  if (collections.includes(selectedCollection)) collectionFilter.value = selectedCollection;

  const modelOptions = f.models || [];
  const models = modelOptions.map((m) => m.value).filter(Boolean);
  modelFilter.innerHTML =
    modelOptions.map((m) => `<option value="${m.value}">${m.value}${m.count ? ` (${m.count})` : ""}</option>`)
      .join("");
  restoreMultiSelection(modelFilter, selectedModels.filter((v) => models.includes(v)));
  if (!selectedModels.length) modelFilter.selectedIndex = -1;

  renderBackdropOptions(f.backdrops || []);
  renderSymbolOptions(f.symbols || []);
}

function renderFavoritesList() {
  const favRows = marketRows.filter((r) => isFavorite(r.gift_id));
  if (favRows.length === 0) {
    favoritesList.innerHTML = '<li class="empty-fav">Список избранного пуст</li>';
    return;
  }
  favoritesList.innerHTML = favRows
    .slice()
    .sort((a, b) => b.change_7d - a.change_7d)
    .map(
      (r) =>
        `<li><button class="fav-open" data-open-gift="${r.gift_id}">${getGiftIcon(r.gift_id)} ${r.name}</button> <span class="tag ${r.signal}">${r.signal}</span> <span class="${clsForValue(r.change_7d)}">${formatPct(r.change_7d)}</span></li>`
    )
    .join("");
}

function renderChart(series) {
  const pricesAll = series.prices_ton && series.prices_ton.length ? series.prices_ton : series.prices;
  const datesAll = Array.isArray(series.dates) ? series.dates : [];
  if (!pricesAll || pricesAll.length === 0) {
    lineChart.innerHTML = "";
    return;
  }

  const targetPoints = Math.min(48, pricesAll.length);
  const pickedIdx = [];
  for (let i = 0; i < targetPoints; i++) {
    pickedIdx.push(Math.round((i * (pricesAll.length - 1)) / Math.max(1, targetPoints - 1)));
  }
  const uniqueIdx = [...new Set(pickedIdx)];
  const prices = uniqueIdx.map((i) => pricesAll[i]);
  const dates = uniqueIdx.map((i) => datesAll[i] || "");

  const max = Math.max(...prices);
  const min = Math.min(...prices);
  const padLeft = 38;
  const padRight = 22;
  const padTop = 14;
  const padBottom = 26;
  const viewW = 1000;
  const viewH = 440;
  const h = viewH - padTop - padBottom;
  const w = viewW - padLeft - padRight;
  const range = max - min || 1;
  const yPad = range * 0.18;
  const yMax = max + yPad;
  const yMin = Math.max(0, min - yPad);
  const yRange = yMax - yMin || 1;

  const pointsRaw = prices.map((price, i) => {
    const x = padLeft + (i / Math.max(1, prices.length - 1)) * w;
    const norm = (price - yMin) / yRange;
    const y = padTop + (1 - norm) * h;
    return { x, y, price };
  });

  const d = pointsRaw.map((p, i) => `${i === 0 ? "M" : "L"} ${p.x.toFixed(2)} ${p.y.toFixed(2)}`).join(" ");
  const areaD = `${d} L ${(padLeft + w).toFixed(2)} ${(padTop + h).toFixed(2)} L ${padLeft.toFixed(2)} ${(padTop + h).toFixed(2)} Z`;

  const yGridCount = 6;
  const xGridCount = 9;
  let grid = "";
  let yAxisLabels = "";
  for (let i = 0; i <= yGridCount; i++) {
    const y = padTop + (i / yGridCount) * h;
    grid += `<line x1="${padLeft}" y1="${y.toFixed(1)}" x2="${(padLeft + w).toFixed(1)}" y2="${y.toFixed(1)}" stroke="#ece7fb" stroke-width="1" />`;
    const val = yMax - (i / yGridCount) * yRange;
    yAxisLabels += `<text x="${(padLeft - 8).toFixed(1)}" y="${(y + 4).toFixed(1)}" text-anchor="end" font-size="11" fill="#8f84ae">${formatTon(val, 2)}</text>`;
  }
  let xAxisLabels = "";
  for (let i = 0; i <= xGridCount; i++) {
    const x = padLeft + (i / xGridCount) * w;
    grid += `<line x1="${x.toFixed(1)}" y1="${padTop}" x2="${x.toFixed(1)}" y2="${(padTop + h).toFixed(1)}" stroke="#f2eefc" stroke-width="1" />`;
    const idx = Math.round((i / xGridCount) * (prices.length - 1));
    const rawDt = dates[idx] || "";
    const dtLabel = rawDt ? String(rawDt).slice(5, 10) : String(idx + 1);
    xAxisLabels += `<text x="${x.toFixed(1)}" y="${(padTop + h + 16).toFixed(1)}" text-anchor="middle" font-size="10" fill="#9b90be">${dtLabel}</text>`;
  }

  const valueStep = Math.max(1, Math.floor(pointsRaw.length / 8));
  const pointsSvg = pointsRaw
    .filter((_, idx) => idx % Math.max(1, Math.floor(pointsRaw.length / 10)) === 0 || idx === pointsRaw.length - 1)
    .map(
      (p) => `
        <circle cx="${p.x.toFixed(2)}" cy="${p.y.toFixed(2)}" r="4.5" fill="#8a61f7" />
        <circle cx="${p.x.toFixed(2)}" cy="${p.y.toFixed(2)}" r="2.1" fill="#fff" />
      `
    )
    .join("");
  const pointValueLabels = pointsRaw
    .filter((_, idx) => idx % valueStep === 0 || idx === pointsRaw.length - 1)
    .map(
      (p) => `
        <text x="${p.x.toFixed(2)}" y="${(p.y - 9).toFixed(2)}" text-anchor="middle" font-size="10" font-weight="700" fill="#5f4aa1">${formatTon(p.price, 2)}</text>
      `
    )
    .join("");

  lineChart.innerHTML = `
    <defs>
      <linearGradient id="areaFill" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="#8a61f7" stop-opacity="0.32"/>
        <stop offset="100%" stop-color="#8a61f7" stop-opacity="0.03"/>
      </linearGradient>
    </defs>
    <rect x="${padLeft}" y="${padTop}" width="${w}" height="${h}" fill="#fff" stroke="#ece6fb" />
    ${grid}
    ${yAxisLabels}
    ${xAxisLabels}
    <path d="${areaD}" fill="url(#areaFill)" />
    <path d="${d}" fill="none" stroke="#8a61f7" stroke-width="3.6" stroke-linecap="round" stroke-linejoin="round" />
    ${pointsSvg}
    ${pointValueLabels}
  `;
}

function renderScreener(rows) {
  const queryRaw = (giftSearch.value || "").trim();
  const queryNorm = normalizeText(queryRaw);
  const filtered = rows.filter((r) => {
    const plain = `${r.name} ${r.gift_id} ${r.collection || ""} ${r.model || ""}`.toLowerCase();
    const norm = normalizeText(`${r.name} ${r.gift_id} ${r.collection || ""} ${r.model || ""}`);
    const matchesSearch = !queryRaw || plain.includes(queryRaw.toLowerCase()) || (queryNorm && norm.includes(queryNorm));
    const matchesFavorite = !favoritesOnly.checked || isFavorite(r.gift_id);
    return matchesSearch && matchesFavorite;
  });

  const totalItems = filtered.length;
  const totalPages = Math.max(1, Math.ceil(totalItems / pageSize));
  if (currentPage > totalPages) currentPage = totalPages;
  const start = (currentPage - 1) * pageSize;
  const end = start + pageSize;
  const pagedRows = filtered.slice(start, end);

  pageInfo.textContent = `Страница ${currentPage}/${totalPages} • ${totalItems}`;
  prevPageBtn.disabled = currentPage <= 1;
  nextPageBtn.disabled = currentPage >= totalPages;

  const grouped = new Map();
  for (const row of pagedRows) {
    const key = row.group || "Other";
    if (!grouped.has(key)) grouped.set(key, []);
    grouped.get(key).push(row);
  }

  const parts = [];
  for (const [groupName, items] of grouped.entries()) {
    parts.push(`<tr class="group-row"><td colspan="10">${groupName} <span class="group-count">${items.length}</span></td></tr>`);
    for (const r of items) {
      parts.push(`
      <tr>
        <td>${renderGiftNameCell(r)}</td>
        <td>${renderFavoriteButton(r.gift_id)}</td>
        <td>${formatTon(r.price_ton ?? 0)}</td>
        <td class="${clsForValue(r.change_1d)}">${formatPct(r.change_1d)}</td>
        <td class="${clsForValue(r.change_7d ?? 0)}">${formatPct(r.change_7d)}</td>
        <td class="${clsForValue(r.change_30d ?? 0)}">${formatPct(r.change_30d)}</td>
        <td>${r.demand_supply_ratio.toFixed(2)}</td>
        <td>${r.volume}</td>
        <td><span class="tag ${r.signal}">${r.signal}</span></td>
        <td>${r.commentary}</td>
      </tr>
    `);
    }
  }

  if (!parts.length) {
    screenerBody.innerHTML = '<tr><td colspan="10">Ничего не найдено</td></tr>';
    return;
  }
  screenerBody.innerHTML = parts.join("");
}

function renderSignals(rows) {
  signalsList.innerHTML = rows
    .slice(0, 8)
    .map(
      (r) =>
        `<li><strong>${getGiftIcon(r.gift_id)} ${r.name}</strong> <span class="tag ${r.signal}">${r.signal}</span> 7д: ${formatPct(r.change_7d)}, D/S: ${r.demand_supply_ratio.toFixed(2)}, z-score: ${r.zscore_30d.toFixed(2)}</li>`
    )
    .join("");
}

function openGiftModal() {
  giftModal.classList.remove("hidden");
}

function closeGiftModal() {
  giftModal.classList.add("hidden");
}

function buildRecentTrend(details) {
  const prices = details.chart_tail?.prices || [];
  if (prices.length < 2) return "Недостаточно данных";
  const start = prices[0];
  const end = prices[prices.length - 1];
  const pct = ((end - start) / (start || 1)) * 100;
  return `${formatPct(pct)} за последние ${prices.length} тиков`;
}

async function showGiftModal(giftId) {
  const resp = await fetchJson(`/api/market/gift-details?gift_id=${encodeURIComponent(giftId)}`);
  const d = resp.data;
  const g = d.gift;
  const p = d.profile || {};
  giftModalTitle.textContent = `${getGiftIcon(g.gift_id)} ${g.name}`;
  giftModalBody.innerHTML = `
    <div class="modal-price-line"><strong>Цена:</strong> ${formatTon(d.price_ton)} TON | ${d.price_stars} ⭐</div>
    <div><strong>Группа:</strong> ${g.group} | <strong>Сигнал:</strong> <span class="tag ${g.signal}">${g.signal}</span></div>
    <div class="modal-grid">
      <div class="modal-kpi"><div class="label">Модель</div><div class="value">${withShare(p.model || "-", p.model_share)}</div></div>
      <div class="modal-kpi"><div class="label">Узор</div><div class="value">${withShare(p.pattern || "-", p.pattern_share)}</div></div>
      <div class="modal-kpi"><div class="label">Фон</div><div class="value">${withShare(p.background || "-", p.background_share)}</div></div>
      <div class="modal-kpi"><div class="label">Наличие</div><div class="value">${p.issued ?? "-"} / ${p.total_supply ?? "-"}</div></div>
      <div class="modal-kpi"><div class="label">Ценность</div><div class="value">${p.value_ton_estimate ? `~${formatTon(p.value_ton_estimate)} TON` : p.value_rub_estimate ? `~${Number(p.value_rub_estimate).toFixed(2)} ₽` : `${p.value_score ?? "-"} / 100`}</div></div>
      <div class="modal-kpi"><div class="label">Изм. 1д</div><div class="value ${clsForValue(g.change_1d)}">${formatPct(g.change_1d)}</div></div>
      <div class="modal-kpi"><div class="label">Изм. 7д</div><div class="value ${clsForValue(g.change_7d ?? 0)}">${formatPct(g.change_7d)}</div></div>
      <div class="modal-kpi"><div class="label">Изм. 30д</div><div class="value ${clsForValue(g.change_30d ?? 0)}">${formatPct(g.change_30d)}</div></div>
      <div class="modal-kpi"><div class="label">Спрос/Предложение</div><div class="value">${g.demand_supply_ratio.toFixed(2)}</div></div>
      <div class="modal-kpi"><div class="label">Объём</div><div class="value">${g.volume}</div></div>
      <div class="modal-kpi"><div class="label">Волатильность 30д</div><div class="value">${g.volatility_30d.toFixed(2)}%</div></div>
    </div>
    <div><strong>Источник профиля:</strong> ${p.source_note || "N/A"}</div>
    <div><strong>Краткий тренд:</strong> ${buildRecentTrend(d)}</div>
    <div><strong>Аналитика:</strong> ${g.commentary}</div>
    <div><a class="buy-link" href="${d.buy_url}" target="_blank" rel="noopener noreferrer">Купить подарок</a></div>
  `;
  openGiftModal();
}

async function fetchJson(url, options = {}) {
  const res = await fetch(url, options);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

async function loadSummary() {
  const resp = await fetchJson("/api/market/summary");
  const summary = normalizeSummary(resp?.data || {});
  lastSummary = summary;
  marketRows = summary.rows;
  renderKpi(summary);
  renderGiftOptions(marketRows);
  renderCollectionOptions(marketRows);
  renderModelOptions(marketRows);
  try {
    await loadFilterOptions();
  } catch (e) {
    console.error("filters load failed", e);
  }
  await loadScreenerFiltered();
  renderFavoritesList();

  if (currentGiftId) {
    await loadChart(currentGiftId);
  }
}

async function loadChart(giftId) {
  const resp = await fetchJson(`/api/market/chart?gift_id=${encodeURIComponent(giftId)}`);
  renderChart(resp.data);
}

async function loadScreenerFiltered() {
  const params = new URLSearchParams();
  if (signalFilter.value) params.set("signal", signalFilter.value);
  if (marketFilter.value) params.set("market", marketFilter.value);
  if (collectionFilter.value) params.set("collection", collectionFilter.value);
  for (const v of getMultiSelectedValues(modelFilter)) params.append("model", v);
  for (const v of getMultiSelectedValues(backdropFilter)) params.append("backdrop", v);
  for (const v of getMultiSelectedValues(symbolFilter)) params.append("symbol", v);
  if (sortBy.value) params.set("sort_by", sortBy.value);
  if (order.value) params.set("order", order.value);

  const resp = await fetchJson(`/api/market/screener?${params.toString()}`);
  renderScreener(resp.data);
}

async function loadSignals() {
  const resp = await fetchJson("/api/signals/latest");
  renderSignals(resp.data);
}

async function loadRealtimeStatus() {
  const resp = await fetchJson("/api/market/realtime-status");
  const st = resp.data;
  if (st.verified_only && st.verified_source === "fragment") {
    liveStatus.textContent = `LIVE: Fragment sync каждые ${st.verified_refresh_sec}s, тиков ${st.realtime_tick_count}, обновлено ${st.last_tick_at || "-"}`;
    return;
  }
  liveStatus.textContent = `LIVE: тик #${st.realtime_tick_count}, шаг ${st.realtime_interval_sec}s, обновлено ${st.last_tick_at || "-"}`;
}

giftSelect.addEventListener("change", () => {
  currentGiftId = giftSelect.value;
  loadChart(currentGiftId);
});

giftModalClose.addEventListener("click", closeGiftModal);
giftModal.addEventListener("click", (e) => {
  if (e.target.dataset.close === "1") closeGiftModal();
});

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeGiftModal();
});

screenerBody.addEventListener("click", async (e) => {
  const favButton = e.target.closest(".fav-btn");
  if (favButton) {
    e.preventDefault();
    try {
      await toggleFavorite(favButton.dataset.favId);
      if (lastSummary) renderKpi(lastSummary);
      await loadScreenerFiltered();
      renderFavoritesList();
    } catch (err) {
      console.error(err);
      alert("Не удалось обновить избранное");
    }
    return;
  }

  const link = e.target.closest(".gift-link");
  if (!link) return;
  e.preventDefault();
  try {
    await showGiftModal(link.dataset.giftId);
  } catch (err) {
    console.error(err);
    alert("Не удалось загрузить детали подарка");
  }
});

favoritesList.addEventListener("click", async (e) => {
  const openBtn = e.target.closest(".fav-open");
  if (!openBtn) return;
  e.preventDefault();
  try {
    await showGiftModal(openBtn.dataset.openGift);
  } catch (err) {
    console.error(err);
  }
});

giftSearch.addEventListener("input", () => {
  currentPage = 1;
  loadScreenerFiltered();
});
favoritesOnly.addEventListener("change", () => {
  currentPage = 1;
  loadScreenerFiltered();
});
collectionFilter.addEventListener("change", () => {
  currentPage = 1;
  renderModelOptions(marketRows);
  loadScreenerFiltered();
});
modelFilter.addEventListener("change", () => {
  currentPage = 1;
  loadScreenerFiltered();
});
backdropFilter.addEventListener("change", () => {
  currentPage = 1;
  loadScreenerFiltered();
});
symbolFilter.addEventListener("change", () => {
  currentPage = 1;
  loadScreenerFiltered();
});
marketFilter.addEventListener("change", () => {
  currentPage = 1;
  loadScreenerFiltered();
});
pageSizeSelect.addEventListener("change", () => {
  pageSize = Number(pageSizeSelect.value) || 25;
  currentPage = 1;
  loadScreenerFiltered();
});
prevPageBtn.addEventListener("click", () => {
  if (currentPage > 1) {
    currentPage -= 1;
    loadScreenerFiltered();
  }
});
nextPageBtn.addEventListener("click", () => {
  currentPage += 1;
  loadScreenerFiltered();
});
refreshBtn.addEventListener("click", async () => {
  refreshBtn.disabled = true;
  try {
    await fetchJson("/api/admin/refresh", { method: "POST" });
    await Promise.all([loadSummary(), loadSignals(), loadRealtimeStatus()]);
  } finally {
    refreshBtn.disabled = false;
  }
});

function startAutoRefresh() {
  if (autoRefreshTimer) clearInterval(autoRefreshTimer);
  autoRefreshTimer = setInterval(async () => {
    try {
      await Promise.all([loadSummary(), loadSignals(), loadRealtimeStatus()]);
    } catch (e) {
      console.error(e);
      liveStatus.textContent = "LIVE: ошибка обновления";
    }
  }, 5000);
}

bindMultiToggle(modelFilter);
bindMultiToggle(backdropFilter);
bindMultiToggle(symbolFilter);
pageSize = Number(pageSizeSelect.value) || 25;
Promise.all([loadFavorites(), loadSummary(), loadSignals(), loadRealtimeStatus()])
  .then(() => startAutoRefresh())
  .catch((e) => {
    console.error(e);
    alert("Ошибка загрузки данных. Проверьте, что сервер запущен.");
  });
