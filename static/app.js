const kpiGrid = document.getElementById("kpiGrid");
const giftSelect = document.getElementById("giftSelect");
const lineChart = document.getElementById("lineChart");
const screenerBody = document.getElementById("screenerBody");
const signalsList = document.getElementById("signalsList");
const applyFilterBtn = document.getElementById("applyFilterBtn");
const refreshBtn = document.getElementById("refreshBtn");
const liveStatus = document.getElementById("liveStatus");
const giftModal = document.getElementById("giftModal");
const giftModalBody = document.getElementById("giftModalBody");
const giftModalTitle = document.getElementById("giftModalTitle");
const giftModalClose = document.getElementById("giftModalClose");

const signalFilter = document.getElementById("signalFilter");
const groupFilter = document.getElementById("groupFilter");
const sortBy = document.getElementById("sortBy");
const order = document.getElementById("order");

let marketRows = [];
let currentGiftId = "";
let autoRefreshTimer = null;

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
  const sign = v > 0 ? "+" : "";
  return `${sign}${v.toFixed(2)}%`;
}

function formatPrice(v) {
  return Number(v).toFixed(2);
}

function renderGiftNameCell(r) {
  return `<a href="#" class="gift-link" data-gift-id="${r.gift_id}">${getGiftIcon(r.gift_id)} ${r.name}</a>`;
}

function renderKpi(data) {
  const items = [
    ["Состояние рынка", data.market_state],
    ["Всего подарков", String(data.rows.length)],
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

function renderGiftOptions(rows) {
  const selectedBefore = currentGiftId || giftSelect.value;
  giftSelect.innerHTML = rows
    .map((r) => `<option value="${r.gift_id}">${getGiftIcon(r.gift_id)} ${r.name}</option>`)
    .join("");
  const hasSelected = rows.some((r) => r.gift_id === selectedBefore);
  currentGiftId = hasSelected && selectedBefore ? selectedBefore : rows[0]?.gift_id || "";
  giftSelect.value = currentGiftId;
}

function renderGroupOptions(rows) {
  const selectedBefore = groupFilter.value || "";
  const groups = [...new Set(rows.map((r) => r.group || "Other"))].sort((a, b) => a.localeCompare(b));
  const options = ['<option value="">Все группы</option>']
    .concat(groups.map((g) => `<option value="${g}">${g}</option>`))
    .join("");
  groupFilter.innerHTML = options;
  if (groups.includes(selectedBefore)) groupFilter.value = selectedBefore;
}

function renderChart(series) {
  const prices = series.prices;
  if (!prices || prices.length === 0) {
    lineChart.innerHTML = "";
    return;
  }
  const max = Math.max(...prices);
  const min = Math.min(...prices);
  const padLeft = 70;
  const padRight = 20;
  const padTop = 22;
  const padBottom = 36;
  const viewW = 1000;
  const viewH = 360;
  const h = viewH - padTop - padBottom;
  const w = viewW - padLeft - padRight;
  const range = max - min || 1;
  const yTicks = 5;

  const points = prices.map((price, i) => {
    const x = padLeft + (i / (prices.length - 1 || 1)) * w;
    const norm = (price - min) / range;
    const y = padTop + (1 - norm) * h;
    return `${x.toFixed(2)},${y.toFixed(2)}`;
  });

  const firstPoint = points[0].split(",");
  const lastPoint = points[points.length - 1].split(",");
  const area = `${firstPoint[0]},${padTop + h} ${points.join(" ")} ${lastPoint[0]},${padTop + h}`;
  const last = prices[prices.length - 1];
  const first = prices[0];
  const trendUp = last >= first;
  const changePct = ((last - first) / (first || 1)) * 100;
  const lineColor = trendUp ? "#0b8f51" : "#c0392b";
  const fillColor = trendUp ? "rgba(11,143,81,0.14)" : "rgba(192,57,43,0.14)";
  const lastX = Number(lastPoint[0]);
  const lastY = Number(lastPoint[1]);

  const yGrid = Array.from({ length: yTicks + 1 }, (_, i) => {
    const t = i / yTicks;
    const y = padTop + t * h;
    const val = max - t * range;
    return `<line x1="${padLeft}" y1="${y.toFixed(1)}" x2="${(padLeft + w).toFixed(1)}" y2="${y.toFixed(1)}" stroke="#d5dee6" stroke-width="1" />
    <text x="${padLeft - 10}" y="${(y + 4).toFixed(1)}" text-anchor="end" fill="#5f6b76" font-size="12">${formatPrice(val)}</text>`;
  }).join("");

  const xTickStep = Math.max(1, Math.floor((prices.length - 1) / 6));
  let xTicks = "";
  for (let i = 0; i < prices.length; i += xTickStep) {
    const x = padLeft + (i / (prices.length - 1 || 1)) * w;
    const raw = String(series.dates[i] || "");
    const label = raw.length > 10 ? raw.slice(11, 16) : raw.slice(5);
    xTicks += `<line x1="${x.toFixed(1)}" y1="${padTop + h}" x2="${x.toFixed(1)}" y2="${padTop + h + 5}" stroke="#b9c7d3" />
    <text x="${x.toFixed(1)}" y="${padTop + h + 20}" text-anchor="middle" fill="#5f6b76" font-size="11">${label}</text>`;
  }
  if ((prices.length - 1) % xTickStep !== 0) {
    const x = padLeft + w;
    const raw = String(series.dates[prices.length - 1] || "");
    const label = raw.length > 10 ? raw.slice(11, 16) : raw.slice(5);
    xTicks += `<line x1="${x.toFixed(1)}" y1="${padTop + h}" x2="${x.toFixed(1)}" y2="${padTop + h + 5}" stroke="#b9c7d3" />
    <text x="${x.toFixed(1)}" y="${padTop + h + 20}" text-anchor="middle" fill="#5f6b76" font-size="11">${label}</text>`;
  }

  lineChart.innerHTML = `
    <rect x="${padLeft}" y="${padTop}" width="${w}" height="${h}" fill="#ffffff" stroke="#d7dde3" />
    ${yGrid}
    ${xTicks}
    <polygon points="${area}" fill="${fillColor}" />
    <polyline fill="none" stroke="${lineColor}" stroke-width="3" points="${points.join(" ")}" />
    <circle cx="${lastX}" cy="${lastY}" r="4.5" fill="${lineColor}" />
    <text x="${padLeft + 10}" y="18" fill="#1c252f" font-size="13" font-weight="600">${series.name}</text>
    <text x="${padLeft + 220}" y="18" fill="${lineColor}" font-size="13" font-weight="700">Текущая: ${formatPrice(last)} (${formatPct(changePct)})</text>
  `;
}

function renderScreener(rows) {
  const grouped = new Map();
  for (const row of rows) {
    const key = row.group || "Other";
    if (!grouped.has(key)) grouped.set(key, []);
    grouped.get(key).push(row);
  }

  const parts = [];
  for (const [groupName, items] of grouped.entries()) {
    parts.push(
      `<tr class="group-row"><td colspan="9">${groupName} <span class="group-count">${items.length}</span></td></tr>`
    );
    for (const r of items) {
      parts.push(`
      <tr>
        <td>${renderGiftNameCell(r)}</td>
        <td>${r.price.toFixed(2)}</td>
        <td class="${clsForValue(r.change_1d)}">${formatPct(r.change_1d)}</td>
        <td class="${clsForValue(r.change_7d)}">${formatPct(r.change_7d)}</td>
        <td class="${clsForValue(r.change_30d)}">${formatPct(r.change_30d)}</td>
        <td>${r.demand_supply_ratio.toFixed(2)}</td>
        <td>${r.volume}</td>
        <td><span class="tag ${r.signal}">${r.signal}</span></td>
        <td>${r.commentary}</td>
      </tr>
    `);
    }
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
  giftModalTitle.textContent = `${getGiftIcon(g.gift_id)} ${g.name}`;
  giftModalBody.innerHTML = `
    <div class="modal-price-line"><strong>Цена:</strong> ${formatPrice(d.price_usd)} USD | ${d.price_ton.toFixed(4)} TON | ${d.price_stars} ⭐</div>
    <div><strong>Группа:</strong> ${g.group} | <strong>Сигнал:</strong> <span class="tag ${g.signal}">${g.signal}</span></div>
    <div class="modal-grid">
      <div class="modal-kpi"><div class="label">Изм. 1д</div><div class="value ${clsForValue(g.change_1d)}">${formatPct(g.change_1d)}</div></div>
      <div class="modal-kpi"><div class="label">Изм. 7д</div><div class="value ${clsForValue(g.change_7d)}">${formatPct(g.change_7d)}</div></div>
      <div class="modal-kpi"><div class="label">Изм. 30д</div><div class="value ${clsForValue(g.change_30d)}">${formatPct(g.change_30d)}</div></div>
      <div class="modal-kpi"><div class="label">Спрос/Предложение</div><div class="value">${g.demand_supply_ratio.toFixed(2)}</div></div>
      <div class="modal-kpi"><div class="label">Объём</div><div class="value">${g.volume}</div></div>
      <div class="modal-kpi"><div class="label">Волатильность 30д</div><div class="value">${g.volatility_30d.toFixed(2)}%</div></div>
    </div>
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
  marketRows = resp.data.rows;
  renderKpi(resp.data);
  renderGiftOptions(marketRows);
  renderGroupOptions(marketRows);
  await loadScreenerFiltered();

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
  if (groupFilter.value) params.set("group", groupFilter.value);
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

applyFilterBtn.addEventListener("click", loadScreenerFiltered);
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

Promise.all([loadSummary(), loadSignals(), loadRealtimeStatus()])
  .then(() => startAutoRefresh())
  .catch((e) => {
    console.error(e);
    alert("Ошибка загрузки данных. Проверьте, что сервер запущен.");
  });
