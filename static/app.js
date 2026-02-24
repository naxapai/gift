const state = {
  starsRate: null,
  overview: null,
  bases: [],
  variants: [],
  selectedBaseId: null,
  watchlist: new Set(JSON.parse(localStorage.getItem("watchlist_variants") || "[]")),
  showStars: localStorage.getItem("show_stars") || "on",
  selectedVariantId: null,
  requestCache: new Map(),
  chart: {
    points: [],
    start: 0,
    end: 1,
    dragging: false,
    dragX: 0,
    period: "24h",
    activeVariantId: null,
  },
  listings: {
    rows: [],
    sortField: "price_ton",
    sortDir: "asc",
  },
  recoDay: {
    pool: [],
    offset: 0,
    timer: null,
  },
  marketAiSignal: {
    items: [],
    lastFetchTs: 0,
    refreshMs: 60 * 60 * 1000,
  },
  mskClockTimer: null,
  overviewSignal: {
    points: [],
    period: "1h",
    topItems: [],
    shockItems: [],
    overheatItems: [],
  },
  variantsCache: {
    loadedAtMs: 0,
    ttlMs: 10 * 60 * 1000,
  },
  autoSync: {
    timer: null,
    inProgress: false,
    intervalMs: 60000,
  },
  pageLoaded: {
    overview: false,
    catalog: false,
    screeners: false,
    signals: false,
    watchlist: false,
    alerts: false,
  },
  signals: {
    filter: "all",
    items: [],
    buyTotal: 0,
    sellTotal: 0,
  },
  ui: {
    catalogFiltersCollapsed: true,
  },
  catalogFilters: {
    baseId: "",
    modelId: "",
    backgroundIds: [],
    patternIds: [],
  },
  auth: {
    required: true,
    enabled: false,
    authenticated: false,
    botUsername: "",
    user: null,
    webappLoginTried: false,
    webappDetected: false,
    webappAutoLoginInFlight: false,
    webappRetryTimer: null,
  },
  ton: {
    required: false,
    connected: false,
    wallet: null,
    localWallet: null,
    connecting: false,
    menuOpen: false,
    balanceTon: null,
    balanceUpdatedAt: 0,
    balanceLoading: false,
    challengeTtlSec: 180,
    proofMaxAgeSec: 300,
    ui: null,
  },
};

const STORAGE_PAGE_KEY = "active_page";
const STORAGE_VARIANT_KEY = "active_variant_id";
const STORAGE_BASE_KEY = "active_base_id";

const el = {
  pages: document.querySelectorAll(".page"),
  navBtns: document.querySelectorAll(".nav-btn"),
  mobileNavBtns: document.querySelectorAll(".mobile-nav-btn"),
  refreshBtn: document.getElementById("refreshBtn"),
  globalSearch: document.getElementById("globalSearch"),
  staleBanner: document.getElementById("staleBanner"),
  toast: document.getElementById("toast"),
  authGate: document.getElementById("authGate"),
  authGateText: document.getElementById("authGateText"),
  authUser: document.getElementById("authUser"),
  telegramLoginWrap: document.getElementById("telegramLoginWrap"),
  headerTonWallet: document.getElementById("headerTonWallet"),
  headerTonConnectBtn: document.getElementById("headerTonConnectBtn"),
  headerTonMenuBtn: document.getElementById("headerTonMenuBtn"),
  headerTonDropdown: document.getElementById("headerTonDropdown"),
  headerTonWalletAddress: document.getElementById("headerTonWalletAddress"),
  headerTonWalletBalance: document.getElementById("headerTonWalletBalance"),
  headerTonWalletConnectedAt: document.getElementById("headerTonWalletConnectedAt"),
  headerTonDisconnectBtn: document.getElementById("headerTonDisconnectBtn"),
  authGateLoginWrap: document.getElementById("authGateLoginWrap"),
  authLogoutBtn: document.getElementById("authLogoutBtn"),
  tonWalletStatus: document.getElementById("tonWalletStatus"),
  tonConnectBtn: document.getElementById("tonConnectBtn"),
  tonDisconnectBtn: document.getElementById("tonDisconnectBtn"),

  updatedAt: document.getElementById("updatedAt"),
  marketState: document.getElementById("marketState"),
  giftCount: document.getElementById("giftCount"),
  collectionCountHero: document.getElementById("collectionCountHero"),
  modelCountHero: document.getElementById("modelCountHero"),
  statusLine: document.getElementById("statusLine"),
  kpiList: document.getElementById("kpiList"),
  recoDayBody: document.getElementById("recoDayBody"),
  marketAiSignalBody: document.getElementById("marketAiSignalBody"),
  topMoversList: document.getElementById("topMoversList"),
  supplyShockList: document.getElementById("supplyShockList"),
  overheatList: document.getElementById("overheatList"),
  overviewSignalChart: document.getElementById("overviewSignalChart"),
  overviewSignalTooltip: document.getElementById("overviewSignalTooltip"),
  overviewSignalPeriod: document.getElementById("overviewSignalPeriod"),

  baseSearch: document.getElementById("baseSearch"),
  catalogFiltersBody: document.getElementById("catalogFiltersBody"),
  catalogFiltersToggleBtn: document.getElementById("catalogFiltersToggleBtn"),
  baseFilterChips: document.getElementById("baseFilterChips"),
  basesBody: document.getElementById("basesBody"),
  catalogBaseSelect: document.getElementById("catalogBaseSelect"),
  catalogModelSelect: document.getElementById("catalogModelSelect"),
  catalogBackgroundSelect: document.getElementById("catalogBackgroundSelect"),
  catalogPatternSelect: document.getElementById("catalogPatternSelect"),
  catalogVariantsBody: document.getElementById("catalogVariantsBody"),

  screenerType: document.getElementById("screenerType"),
  screenersBody: document.getElementById("screenersBody"),
  signalsBody: document.getElementById("signalsBody"),
  signalsStats: document.getElementById("signalsStats"),
  signalFilterAll: document.getElementById("signalFilterAll"),
  signalFilterBuy: document.getElementById("signalFilterBuy"),
  signalFilterSell: document.getElementById("signalFilterSell"),

  watchlistBody: document.getElementById("watchlistBody"),

  addAlertBtn: document.getElementById("addAlertBtn"),
  alertsJson: document.getElementById("alertsJson"),

  showStars: document.getElementById("showStars"),

  baseTitle: document.getElementById("baseTitle"),
  baseFloor: document.getElementById("baseFloor"),
  baseListings: document.getElementById("baseListings"),
  baseMeta: document.getElementById("baseMeta"),
  baseVariantsBody: document.getElementById("baseVariantsBody"),
  backToCatalogFromBase: document.getElementById("backToCatalogFromBase"),

  variantTitle: document.getElementById("variantTitle"),
  variantPreview: document.getElementById("variantPreview"),
  variantFloor: document.getElementById("variantFloor"),
  variantDeltaGrid: document.getElementById("variantDeltaGrid"),
  variantRecoChip: document.getElementById("variantRecoChip"),
  variantKpi: document.getElementById("variantKpi"),
  variantRecoBody: document.getElementById("variantRecoBody"),
  variantListingsBody: document.getElementById("variantListingsBody"),
  variantChart: document.getElementById("variantChart"),
  chartWrap: document.getElementById("chartWrap"),
  chartTooltip: document.getElementById("chartTooltip"),
  chartPeriod: document.getElementById("chartPeriod"),
  chartReset: document.getElementById("chartReset"),
  listingsSortField: document.getElementById("listingsSortField"),
  listingsSortDir: document.getElementById("listingsSortDir"),
  backToCatalog: document.getElementById("backToCatalog"),
};

const customSelectRegistry = new Map();
let eventsBound = false;
let bootstrapped = false;

function formatTon(value) {
  if (value == null || Number.isNaN(Number(value))) return "-";
  const n = Number(value);
  if (Math.abs(n) < 1) return n.toFixed(3);
  if (Math.abs(n) < 100) return n.toFixed(2);
  return n.toFixed(1);
}

function formatPct(value) {
  if (value == null || Number.isNaN(Number(value))) return "-";
  const n = Number(value);
  return `${Math.abs(n).toFixed(1)}%`;
}

function formatDateTime(value) {
  if (!value) return "-";
  const d = new Date(String(value));
  if (Number.isNaN(d.getTime())) {
    const s = String(value).trim();
    const m = s.match(/^(\d{4}-\d{2}-\d{2})[T\s](\d{2}:\d{2}:\d{2})/);
    if (m) return `${m[1]}/${m[2]}`;
    return s.replace("T", "/").replace("Z", "");
  }
  return formatMskDateTime(d);
}

function formatMskDateTime(date) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Europe/Moscow",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).formatToParts(date);
  const map = Object.fromEntries(parts.map((p) => [p.type, p.value]));
  return `${map.year}-${map.month}-${map.day}/${map.hour}:${map.minute}:${map.second}`;
}

function startMskClock() {
  if (state.mskClockTimer) return;
  const tick = () => {
    el.updatedAt.textContent = `${formatMskDateTime(new Date())} МСК`;
  };
  tick();
  state.mskClockTimer = setInterval(tick, 1000);
}

function metricDelta(metrics, windowLabel) {
  const m = metrics || {};
  const priceKey = `price_change_pct_${windowLabel}`;
  const floorKey = `floor_change_pct_${windowLabel}`;
  const v = m[priceKey];
  if (v != null && !Number.isNaN(Number(v)) && Math.abs(Number(v)) > 0.0001) return Number(v);
  return Number(m[floorKey] || 0);
}

function formatStars(value) {
  if (value == null || Number.isNaN(Number(value))) return "-";
  if (state.showStars === "off") return "-";
  const n = Number(value);
  if (n < 1000) return `${Math.round(n)}`;
  if (n < 10000) return `${(n / 1000).toFixed(1)}k`;
  if (n < 100000) return `${Math.round(n / 1000)}k`;
  return `${(n / 1000).toFixed(1)}k`;
}

function starsFromTon(ton) {
  if (!state.starsRate || state.starsRate.stars_per_ton == null) return null;
  return Number(ton) * Number(state.starsRate.stars_per_ton);
}

function renderGiftIcon(url, title, cls = "gift-icon") {
  const safeUrl = (url || "").trim();
  if (!safeUrl) {
    return `<span class="${cls} gift-icon-fallback" aria-hidden="true">?</span>`;
  }
  return `<img class="${cls}" src="${safeUrl}" alt="${title || "подарок"}" loading="lazy" decoding="async" />`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function actionLabel(action) {
  const code = String(action || "HOLD").toUpperCase();
  const map = {
    BUY: "Покупать",
    SELL: "Продавать",
    HOLD: "Держать",
    WATCH: "Наблюдать",
    AVOID: "Избегать",
  };
  return map[code] || code;
}

function saleTypeLabel(value) {
  const v = String(value || "").toUpperCase();
  if (v === "AUCTION") return "Аукцион";
  if (v === "FIXED") return "Фикс";
  return value || "-";
}

function statusLabel(value) {
  const v = String(value || "").toUpperCase();
  if (v === "ACTIVE") return "Активен";
  if (v === "SOLD") return "Продан";
  return value || "-";
}

function percentClass(v) {
  const n = Number(v || 0);
  if (n > 0) return "color: var(--success)";
  if (n < 0) return "color: var(--danger)";
  return "";
}

function showToast(message) {
  el.toast.textContent = message;
  el.toast.classList.remove("hidden");
  setTimeout(() => el.toast.classList.add("hidden"), 2200);
}

function setPage(pageId) {
  el.pages.forEach((p) => p.classList.remove("active"));
  const pageEl = document.getElementById(pageId);
  if (!pageEl) return;
  pageEl.classList.add("active");
  pageEl.classList.remove("page-switch-in");
  // Small one-shot transition for page switch without long-running animations.
  requestAnimationFrame(() => pageEl.classList.add("page-switch-in"));
  [...el.navBtns, ...el.mobileNavBtns].forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.page === pageId);
  });
  localStorage.setItem(STORAGE_PAGE_KEY, pageId);
  if (window.location.hash !== `#${pageId}`) {
    history.replaceState(null, "", `#${pageId}`);
  }
  ensurePageData(pageId).catch(() => {});
}

async function fetchJson(url, options = {}, useCache = false) {
  if (useCache && state.requestCache.has(url)) {
    return state.requestCache.get(url);
  }
  const requestOptions = {
    credentials: "same-origin",
    ...options,
  };
  const req = fetch(url, requestOptions).then(async (res) => {
    let payload = null;
    try {
      payload = await res.json();
    } catch (e) {
      payload = null;
    }
    if (!res.ok) {
      const details = payload?.reason || payload?.message || payload?.error || "";
      throw new Error(details ? `HTTP ${res.status}: ${details}` : `HTTP ${res.status}: ${url}`);
    }
    return payload || {};
  });
  if (useCache) state.requestCache.set(url, req);
  const data = await req;
  return data;
}

async function waitForManualRefreshDone(timeoutMs = 120000, pollMs = 2000) {
  const startedAt = Date.now();
  while ((Date.now() - startedAt) < timeoutMs) {
    try {
      const st = await fetchJson("/api/admin/refresh/status", { cache: "no-store" });
      if (!st?.running) return st || {};
    } catch (e) {
      // ignore and continue polling
    }
    await new Promise((resolve) => setTimeout(resolve, pollMs));
  }
  return null;
}

function authDisplayName(user) {
  if (!user) return "";
  const first = String(user.first_name || "").trim();
  const last = String(user.last_name || "").trim();
  const full = `${first} ${last}`.trim();
  if (full) return full;
  const username = String(user.username || "").trim();
  if (username) return `@${username}`;
  return `ID ${user.id ?? "-"}`;
}

function setAuthLocked(locked, text = "") {
  document.body.classList.toggle("auth-locked", locked);
  if (el.authGate) {
    el.authGate.classList.toggle("hidden", !locked);
  }
  if (locked && text) {
    el.authGateText.textContent = text;
  }
}

function setCatalogFiltersCollapsed(collapsed) {
  state.ui.catalogFiltersCollapsed = Boolean(collapsed);
  if (el.catalogFiltersBody) {
    el.catalogFiltersBody.classList.toggle("hidden", state.ui.catalogFiltersCollapsed);
  }
  if (el.catalogFiltersToggleBtn) {
    el.catalogFiltersToggleBtn.classList.toggle("expanded", !state.ui.catalogFiltersCollapsed);
    el.catalogFiltersToggleBtn.setAttribute("aria-expanded", state.ui.catalogFiltersCollapsed ? "false" : "true");
    el.catalogFiltersToggleBtn.setAttribute("aria-label", state.ui.catalogFiltersCollapsed ? "Развернуть фильтры" : "Свернуть фильтры");
  }
}

function detectTelegramMiniAppContext() {
  const href = String(window.location.href || "");
  if (/[?&#]tgWebAppData=/.test(href) || /[?&#]tgWebAppVersion=/.test(href) || /[?&#]tgWebAppPlatform=/.test(href)) {
    return true;
  }
  const ua = String(navigator.userAgent || "");
  return /Telegram/i.test(ua);
}

function renderTelegramWidget(container) {
  if (!container) return;
  if (container.querySelector("iframe")) return;
  container.innerHTML = "";
  if (!state.auth.enabled || !state.auth.botUsername) return;

  const callbackUrl = `${window.location.origin}/api/auth/telegram/callback`;
  const renderIframeFallback = () => {
    if (container.querySelector("iframe")) return;
    const origin = encodeURIComponent(window.location.origin);
    const authUrl = encodeURIComponent(callbackUrl);
    const src = `https://oauth.telegram.org/embed/${encodeURIComponent(state.auth.botUsername)}?origin=${origin}&request_access=write&size=large&userpic=false&auth_url=${authUrl}`;
    container.innerHTML = `<iframe src="${src}" width="238" height="52" frameborder="0" scrolling="no" title="Telegram Login"></iframe>`;
  };

  const script = document.createElement("script");
  script.async = true;
  script.src = "https://telegram.org/js/telegram-widget.js?22";
  script.setAttribute("data-telegram-login", state.auth.botUsername);
  script.setAttribute("data-size", "large");
  script.setAttribute("data-radius", "8");
  script.setAttribute("data-userpic", "false");
  script.setAttribute("data-request-access", "write");
  script.setAttribute("data-auth-url", callbackUrl);
  script.onerror = () => renderIframeFallback();
  container.appendChild(script);

  // Safari/adblock fallback: if script loaded but button iframe wasn't injected.
  setTimeout(() => {
    if (!container.querySelector("iframe")) {
      renderIframeFallback();
    }
  }, 1200);
}

function renderAuthUi() {
  const isLoggedIn = Boolean(state.auth.authenticated && state.auth.user);
  const mustLogin = Boolean(state.auth.required && !isLoggedIn);
  const authEnabled = Boolean(state.auth.enabled);
  const webAppMode = Boolean(state.auth.webappDetected);
  const hasWebAppObject = Boolean(window.Telegram && window.Telegram.WebApp);
  const bot = encodeURIComponent(state.auth.botUsername || "");
  const openMiniAppUrl = bot ? `https://t.me/${bot}?startapp=auth` : "";

  if (isLoggedIn) {
    el.authUser.textContent = authDisplayName(state.auth.user);
    el.authUser.classList.remove("hidden");
    el.authLogoutBtn.classList.remove("hidden");
    el.telegramLoginWrap.classList.add("hidden");
    el.telegramLoginWrap.innerHTML = "";
    el.authGateLoginWrap.innerHTML = "";
    setAuthLocked(false);
    return;
  }

  el.authUser.classList.add("hidden");
  el.authLogoutBtn.classList.add("hidden");
  el.telegramLoginWrap.classList.add("hidden");
  el.telegramLoginWrap.innerHTML = "";
  if (authEnabled) {
    if (!webAppMode || !hasWebAppObject) {
      renderTelegramWidget(el.authGateLoginWrap);
      if (bot) {
        el.authGateLoginWrap.insertAdjacentHTML(
          "beforeend",
          `<a class="tg-widget-fallback" style="margin-left:8px" href="https://t.me/${bot}" target="_blank" rel="noopener">Войти через Telegram</a>`
        );
      }
      if (openMiniAppUrl) {
        el.authGateLoginWrap.insertAdjacentHTML(
          "beforeend",
          `<div class="muted small" style="margin-top:10px">Если открыли во внешнем браузере: <a href="${openMiniAppUrl}" target="_blank" rel="noopener">открыть Mini App в Telegram</a></div>`
        );
      }
    } else {
      el.authGateLoginWrap.innerHTML = `
        <div class="muted small">Авторизация внутри Telegram…</div>
        <button id="webappRetryBtn" class="btn secondary" style="margin-top:10px">Повторить вход</button>
        ${openMiniAppUrl ? `<div class="muted small" style="margin-top:8px"><a href="${openMiniAppUrl}" target="_blank" rel="noopener">Открыть Mini App</a></div>` : ""}
      `;
      const retryBtn = document.getElementById("webappRetryBtn");
      if (retryBtn) {
        retryBtn.addEventListener("click", async () => {
          await tryTelegramWebAppLogin();
          await refreshAuthMe();
          renderAuthUi();
        });
      }
    }
  } else {
    const msg = "Telegram Auth не настроен на сервере (TELEGRAM_BOT_TOKEN / TELEGRAM_BOT_USERNAME).";
    el.telegramLoginWrap.innerHTML = "";
    el.authGateLoginWrap.innerHTML = `<span class="muted small">${msg}</span>`;
  }
  if (mustLogin) {
    setAuthLocked(true, "Для доступа к аналитике выполните вход через Telegram.");
  } else {
    setAuthLocked(false);
  }
}

async function refreshAuthMe() {
  try {
    const me = await fetchJson("/api/auth/me", { cache: "no-store" });
    state.auth.required = Boolean(me.required);
    state.auth.enabled = Boolean(me.enabled);
    state.auth.authenticated = Boolean(me.authenticated);
    state.auth.user = me.user || null;
  } catch (e) {
    state.auth.authenticated = false;
    state.auth.user = null;
  }
}

async function initAuth() {
  try {
    const boot = await fetchJson("/api/auth/bootstrap", { cache: "no-store" });
    state.auth.required = Boolean(boot.required);
    state.auth.enabled = Boolean(boot.enabled);
    state.auth.botUsername = String(boot.bot_username || "").trim();
    state.auth.authenticated = Boolean(boot.authenticated);
    state.auth.user = boot.user || null;
  } catch (e) {
    try {
      const cfg = await fetchJson("/api/auth/config", { cache: "no-store" });
      state.auth.required = Boolean(cfg.required);
      state.auth.enabled = Boolean(cfg.enabled);
      state.auth.botUsername = String(cfg.bot_username || "").trim();
      await refreshAuthMe();
    } catch (_e) {
      state.auth.required = true;
      state.auth.enabled = false;
      state.auth.botUsername = "";
    }
  }
  renderAuthUi();
  return !state.auth.required || state.auth.authenticated;
}

async function tryTelegramWebAppLogin() {
  if (state.auth.webappAutoLoginInFlight) return false;
  if (detectTelegramMiniAppContext()) {
    state.auth.webappDetected = true;
  }
  const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
  if (!tg) return false;
  state.auth.webappDetected = true;
  if (typeof tg.ready === "function") {
    try {
      tg.ready();
    } catch (_e) {}
  }
  const initData = String(tg.initData || "").trim();
  if (!initData) return false;
  state.auth.webappAutoLoginInFlight = true;
  try {
    await fetchJson("/api/auth/telegram/webapp-login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ init_data: initData }),
      cache: "no-store",
    });
    state.auth.webappLoginTried = true;
    await refreshAuthMe();
    renderAuthUi();
    state.auth.webappAutoLoginInFlight = false;
    return true;
  } catch (e) {
    state.auth.webappAutoLoginInFlight = false;
    return false;
  }
}

function scheduleWebAppAuthRetry() {
  if (!state.auth.webappDetected) return;
  if (state.auth.webappRetryTimer) return;
  let attempts = 0;
  const maxAttempts = 120;
  state.auth.webappRetryTimer = setInterval(async () => {
    if (!state.auth.required || state.auth.authenticated) {
      clearInterval(state.auth.webappRetryTimer);
      state.auth.webappRetryTimer = null;
      return;
    }
    attempts += 1;
    const ok = await tryTelegramWebAppLogin();
    if (ok || attempts >= maxAttempts) {
      clearInterval(state.auth.webappRetryTimer);
      state.auth.webappRetryTimer = null;
      if (!ok && state.auth.required && !state.auth.authenticated) {
        el.authGateLoginWrap.innerHTML = `<button id="webappRetryBtn" class="btn secondary">Повторить вход в Telegram</button>`;
        const btn = document.getElementById("webappRetryBtn");
        if (btn) btn.addEventListener("click", async () => {
          el.authGateLoginWrap.innerHTML = `<div class="muted small">Авторизация внутри Telegram…</div>`;
          state.auth.webappLoginTried = false;
          scheduleWebAppAuthRetry();
        }, { once: true });
      }
    }
  }, 500);
}

window.onTelegramAuth = async function onTelegramAuth(user) {
  try {
    await fetchJson("/api/auth/telegram/verify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(user || {}),
      cache: "no-store",
    });
    await refreshAuthMe();
    renderAuthUi();
    state.requestCache.clear();
    await loadAll();
    startAutoSync();
    showToast("Вход выполнен");
  } catch (e) {
    showToast("Ошибка входа Telegram");
    await refreshAuthMe();
    renderAuthUi();
  }
};

function shortTonAddress(addr) {
  const a = String(addr || "").trim();
  if (!a) return "-";
  if (a.length < 16) return a;
  return `${a.slice(0, 8)}...${a.slice(-6)}`;
}

function formatTonConnectedAt(wallet) {
  const ts = Number(wallet?.verified_at || 0);
  if (!Number.isFinite(ts) || ts <= 0) return "-";
  return `${formatMskDateTime(new Date(ts * 1000))} МСК`;
}

function closeTonWalletDropdown() {
  state.ton.menuOpen = false;
  if (el.headerTonDropdown) el.headerTonDropdown.classList.add("hidden");
  if (el.headerTonMenuBtn) {
    el.headerTonMenuBtn.classList.remove("open");
    el.headerTonMenuBtn.setAttribute("aria-expanded", "false");
  }
}

async function refreshTonBalance(force = false) {
  const wallet = state.ton.wallet;
  if (!state.ton.connected || !wallet?.address) return;
  const now = Date.now();
  if (!force && state.ton.balanceUpdatedAt && now - state.ton.balanceUpdatedAt < 30000) return;
  if (state.ton.balanceLoading) return;
  state.ton.balanceLoading = true;
  renderTonWalletUi();
  try {
    const resp = await fetchJson("/api/auth/ton/balance", { cache: "no-store" });
    const tonBalance = Number(resp?.ton_balance);
    state.ton.balanceTon = Number.isFinite(tonBalance) ? tonBalance : null;
    state.ton.balanceUpdatedAt = Date.now();
  } catch (e) {
    state.ton.balanceTon = null;
  } finally {
    state.ton.balanceLoading = false;
    renderTonWalletUi();
  }
}

function toggleTonWalletDropdown(force) {
  if (!state.ton.connected) return;
  const open = typeof force === "boolean" ? force : !state.ton.menuOpen;
  state.ton.menuOpen = open;
  if (el.headerTonDropdown) el.headerTonDropdown.classList.toggle("hidden", !open);
  if (el.headerTonMenuBtn) {
    el.headerTonMenuBtn.classList.toggle("open", open);
    el.headerTonMenuBtn.setAttribute("aria-expanded", open ? "true" : "false");
  }
  if (open) {
    refreshTonBalance(false);
  }
}

function tonLocalWalletFromUi() {
  const w = state.ton?.ui?.wallet;
  const account = w?.account || {};
  const address = String(account.address || "").trim();
  if (!address) return null;
  return {
    address,
    chain: account.chain || "-",
  };
}

function renderTonWalletUi() {
  if (!el.tonWalletStatus || !el.tonConnectBtn || !el.tonDisconnectBtn) return;
  if (el.headerTonConnectBtn) {
    if (state.ton.connecting) {
      el.headerTonConnectBtn.textContent = "Подключение TON...";
    } else {
      el.headerTonConnectBtn.textContent = state.ton.connected ? "TON подключен" : "Подключить TON";
    }
    el.headerTonConnectBtn.disabled = Boolean(state.ton.connecting);
  }
  if (el.headerTonMenuBtn) {
    el.headerTonMenuBtn.classList.toggle("hidden", !state.ton.connected);
    el.headerTonMenuBtn.disabled = Boolean(state.ton.connecting || !state.ton.connected);
  }
  el.tonConnectBtn.disabled = Boolean(state.ton.connecting);
  el.tonDisconnectBtn.disabled = Boolean(state.ton.connecting);
  if (state.ton.connecting) {
    closeTonWalletDropdown();
    el.tonWalletStatus.textContent = "Статус: выполняется подключение TON...";
    el.tonConnectBtn.textContent = "Подключение...";
    return;
  }
  if (state.ton.connected && state.ton.wallet) {
    const w = state.ton.wallet;
    el.tonWalletStatus.innerHTML = `Статус: подключен • <strong>${shortTonAddress(w.address)}</strong> • ${w.chain || "-"} • подтвержден`;
    el.tonDisconnectBtn.classList.remove("hidden");
    el.tonConnectBtn.textContent = "Переподключить TON";
    if (el.headerTonWalletAddress) el.headerTonWalletAddress.textContent = shortTonAddress(w.address);
    if (el.headerTonWalletConnectedAt) el.headerTonWalletConnectedAt.textContent = formatTonConnectedAt(w);
    if (el.headerTonWalletBalance) {
      if (state.ton.balanceLoading) {
        el.headerTonWalletBalance.textContent = "Обновление...";
      } else {
        el.headerTonWalletBalance.textContent = state.ton.balanceTon == null ? "- TON" : `${formatTon(state.ton.balanceTon)} TON`;
      }
    }
  } else if (state.ton.localWallet) {
    closeTonWalletDropdown();
    const w = state.ton.localWallet;
    el.tonWalletStatus.innerHTML = `Статус: подключен в кошельке • <strong>${shortTonAddress(w.address)}</strong> • ${w.chain || "-"} • ожидание подтверждения`;
    el.tonDisconnectBtn.classList.remove("hidden");
    el.tonConnectBtn.textContent = "Завершить подключение TON";
    if (el.headerTonWalletAddress) el.headerTonWalletAddress.textContent = shortTonAddress(w.address);
    if (el.headerTonWalletConnectedAt) el.headerTonWalletConnectedAt.textContent = "-";
    if (el.headerTonWalletBalance) el.headerTonWalletBalance.textContent = "- TON";
  } else {
    closeTonWalletDropdown();
    el.tonWalletStatus.textContent = "Статус: не подключен";
    el.tonDisconnectBtn.classList.add("hidden");
    el.tonConnectBtn.textContent = "Подключить TON";
    if (el.headerTonWalletAddress) el.headerTonWalletAddress.textContent = "-";
    if (el.headerTonWalletConnectedAt) el.headerTonWalletConnectedAt.textContent = "-";
    if (el.headerTonWalletBalance) el.headerTonWalletBalance.textContent = "- TON";
  }
}

async function refreshTonMe() {
  try {
    const me = await fetchJson("/api/auth/ton/me", { cache: "no-store" });
    state.ton.connected = Boolean(me.connected);
    state.ton.wallet = me.wallet || null;
    if (state.ton.connected) {
      state.ton.localWallet = null;
    } else {
      state.ton.balanceTon = null;
      state.ton.balanceUpdatedAt = 0;
      state.ton.localWallet = tonLocalWalletFromUi();
    }
    state.ton.required = Boolean(me.required);
  } catch (e) {
    state.ton.connected = false;
    state.ton.wallet = null;
    state.ton.balanceTon = null;
    state.ton.balanceUpdatedAt = 0;
    state.ton.localWallet = tonLocalWalletFromUi();
  }
  if (!state.ton.connected) closeTonWalletDropdown();
  renderTonWalletUi();
}

async function initTonAuth() {
  try {
    const cfg = await fetchJson("/api/auth/ton/config", { cache: "no-store" });
    state.ton.required = Boolean(cfg.required);
    state.ton.challengeTtlSec = Number(cfg.challenge_ttl_sec || 180);
    state.ton.proofMaxAgeSec = Number(cfg.proof_max_age_sec || 300);
  } catch (e) {
    // noop
  }
  await refreshTonMe();

  if (!window.TON_CONNECT_UI || !window.TON_CONNECT_UI.TonConnectUI) {
    el.tonConnectBtn.disabled = true;
    const hint = document.getElementById("tonConnectHint");
    if (hint) hint.textContent = "TonConnect SDK не загружен";
    return;
  }
  if (!state.ton.ui) {
    state.ton.ui = new window.TON_CONNECT_UI.TonConnectUI({
      manifestUrl: `${window.location.origin}/tonconnect-manifest.json`,
      buttonRootId: null,
    });
  }
  try {
    if (state.ton.ui.connectionRestored && typeof state.ton.ui.connectionRestored.then === "function") {
      await state.ton.ui.connectionRestored;
    }
  } catch (e) {
    // noop
  }
  state.ton.localWallet = tonLocalWalletFromUi();
  renderTonWalletUi();
}

async function verifyTonWalletSession(account, proof) {
  return fetchJson("/api/auth/ton/verify", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      account,
      ton_proof: proof || null,
    }),
    cache: "no-store",
  });
}

async function connectTonWallet() {
  if (!state.ton.ui) {
    showToast("TonConnect недоступен");
    return;
  }
  if (state.ton.connecting) return;
  state.ton.connecting = true;
  renderTonWalletUi();
  try {
    if (state.ton.connected) {
      showToast("TON кошелек уже подключен");
      return;
    }

    // If wallet is already connected in TonConnect, first try to complete server session
    // without reconnecting/scanning QR again.
    if (state.ton.ui.wallet && !state.ton.connected) {
      const currentAccount = state.ton.ui.wallet?.account || null;
      if (currentAccount?.address) {
        await verifyTonWalletSession(currentAccount, null);
        await refreshTonMe();
        if (state.ton.connected) {
          showToast("TON кошелек подключен");
          return;
        }
      }
      try {
        await state.ton.ui.disconnect();
      } catch (e) {
        // noop
      }
    }
    const challengeResp = await fetchJson("/api/auth/ton/challenge", {
      method: "POST",
      cache: "no-store",
    });
    const challenge = String(challengeResp.challenge || "");
    if (!challenge) throw new Error("challenge_missing");
    const connected = await state.ton.ui.connectWallet({
      tonProof: challenge,
    });
    state.ton.localWallet = {
      address: connected?.account?.address || "",
      chain: connected?.account?.chain || "-",
    };
    renderTonWalletUi();
    const proof = connected?.connectItems?.tonProof?.proof;
    const account = connected?.account;
    if (!account) throw new Error("ton_account_missing");
    await verifyTonWalletSession(account, proof);
    await refreshTonMe();
    showToast("TON кошелек подключен");
  } catch (e) {
    const message = String(e?.message || e || "");
    showToast(`Ошибка TON: ${message}`);
    await refreshTonMe();
  } finally {
    state.ton.connecting = false;
    renderTonWalletUi();
  }
}

async function disconnectTonWallet() {
  try {
    await fetchJson("/api/auth/ton/logout", { method: "POST", cache: "no-store" });
  } catch (e) {
    // noop
  }
  if (state.ton.ui) {
    try {
      await state.ton.ui.disconnect();
    } catch (e) {
      // noop
    }
  }
  state.ton.localWallet = null;
  state.ton.balanceTon = null;
  state.ton.balanceUpdatedAt = 0;
  closeTonWalletDropdown();
  await refreshTonMe();
  showToast("TON кошелек отключен");
}

function normalizeOverviewError(raw) {
  const text = String(raw || "");
  if (!text) return "";
  if (text === "RESTORED_FROM_LOCAL_SNAPSHOT") return "";
  if (text === "BOOTSTRAP_FROM_VERIFIED_FILE") return "";
  if (text.includes("CERTIFICATE_VERIFY_FAILED")) {
    return "SSL Fragment: ошибка цепочки сертификатов (локальное окружение).";
  }
  return text;
}

function renderOverview(overview) {
  state.overview = overview;
  startMskClock();
  el.updatedAt.title = `Последнее обновление данных: ${formatDateTime(overview.updated_at)} МСК`;
  const marketStateText = String(overview.market_state || "-");
  el.marketState.textContent = marketStateText;
  el.marketState.classList.remove("market-state-up", "market-state-down");
  const marketStateNorm = marketStateText.toLowerCase();
  if (marketStateNorm.includes("рост") || marketStateNorm.includes("bull")) {
    el.marketState.classList.add("market-state-up");
  } else if (marketStateNorm.includes("пад") || marketStateNorm.includes("сниж") || marketStateNorm.includes("bear")) {
    el.marketState.classList.add("market-state-down");
  }
  el.giftCount.textContent = overview.gifts_count ?? overview.active_listings ?? 0;
  el.collectionCountHero.textContent = overview.base_count ?? 0;
  el.modelCountHero.textContent = overview.model_count ?? 0;
  const err = normalizeOverviewError(overview.last_error);
  el.statusLine.textContent = err ? `Ошибка: ${err}` : `Задержка: ${overview.ingestion_lag_seconds ?? "-"}с`;

  el.staleBanner.classList.toggle("hidden", !overview.data_stale);

  const kpis = [
    ["Кол-во коллекций", overview.base_count],
    ["Мин. цена", `${formatTon(overview.floor_ton_min)} TON`],
    ["Медиана цены", `${formatTon(overview.floor_ton_median)} TON`],
    ["Активные лоты", overview.active_listings],
    ["Всего в продаже", overview.total_for_sale ?? overview.active_listings ?? 0],
    ["Всего продано", overview.total_sold ?? 0],
    ["Среднее 7д", formatPct(overview.avg_change_7d || 0)],
    ["Среднее 30д", formatPct(overview.avg_change_30d || 0)],
    ["Сигналы покупки", overview.buy_signals ?? 0],
    ["Сигналы продажи", overview.sell_signals ?? 0],
    ["Аномалии", overview.anomalies],
    ["Курс в ⭐", state.starsRate?.stars_per_ton ? `${Math.round(state.starsRate.stars_per_ton)}` : "н/д"],
  ];
  el.kpiList.innerHTML = kpis
    .map(
      ([k, v]) => `<div class="kpi-item"><div class="kpi-key">${k}</div><div class="kpi-value">${v}</div></div>`
    )
    .join("");
}

function shortListDelta(item, mode) {
  const m = item?.metrics || {};
  const pick = (values) => {
    for (const v of values) {
      const n = Number(v || 0);
      if (Math.abs(n) > 0.0001) return n;
    }
    return Number(values?.[0] || 0);
  };
  if (mode === "supply") {
    return pick([
      m.supply_change_pct_24h,
      m.supply_change_pct_12h,
      m.supply_change_pct_1h,
      m.supply_change_pct_7d,
      m.supply_change_pct_30d,
    ]);
  }
  if (mode === "risk") {
    return pick([
      Number(m.pump_risk_24h || 0) * 100,
      Number(m.volatility_24h || 0) * 100,
      m.price_change_pct_24h,
      m.floor_change_pct_24h,
      m.price_change_pct_12h,
      m.floor_change_pct_12h,
      m.price_change_pct_1h,
      m.floor_change_pct_1h,
    ]);
  }
  return pick([
    m.price_change_pct_24h,
    m.floor_change_pct_24h,
    m.price_change_pct_12h,
    m.floor_change_pct_12h,
    m.price_change_pct_1h,
    m.floor_change_pct_1h,
    m.price_change_pct_7d,
    m.floor_change_pct_7d,
    m.price_change_pct_30d,
    m.floor_change_pct_30d,
  ]);
}

function renderShortList(target, items, emptyText, mode = "price") {
  if (!items.length) {
    target.innerHTML = `<div class="empty-state">${emptyText}</div>`;
    return;
  }
  target.innerHTML = items
    .slice(0, 5)
    .map((item) => {
      const delta = shortListDelta(item, mode);
      const icon = renderGiftIcon(item.preview_url, item.title || item.variant_id, "gift-icon-sm");
      return `<div class="table-row">
        <button class="btn ghost open-variant gift-cell" data-variant="${item.variant_id}">${icon}<span>${item.title || item.variant_id}</span></button>
        <span>${formatTon(item.metrics?.floor_ton)} TON</span>
        <span style="${percentClass(delta)}">${formatPct(delta)}</span>
      </div>`;
    })
    .join("");
}

function sumPressure(items, windowLabel, side = "buy") {
  let total = 0;
  for (const item of items || []) {
    const d = Number(metricDelta(item?.metrics, windowLabel) || 0);
    if (side === "buy" && d > 0) total += d;
    if (side === "sell" && d < 0) total += Math.abs(d);
  }
  return total;
}

function interpolateAnchors(anchors, segments = 8) {
  if (!anchors?.length) return [];
  const out = [];
  for (let i = 0; i < anchors.length - 1; i++) {
    const a = anchors[i];
    const b = anchors[i + 1];
    for (let s = 0; s < segments; s++) {
      const t = s / segments;
      out.push({
        x: i * segments + s,
        buy: a.buy + (b.buy - a.buy) * t,
        sell: a.sell + (b.sell - a.sell) * t,
        label: a.label,
      });
    }
  }
  const last = anchors[anchors.length - 1];
  out.push({ x: (anchors.length - 1) * segments, buy: last.buy, sell: last.sell, label: last.label });
  return out;
}

function buildOverviewSignalSeries(topItems, shockItems, overheatItems) {
  const period = String(state.overviewSignal?.period || "1h");
  const periodSec = periodSeconds(period);
  const largerByPeriod = { "1h": "12h", "12h": "24h", "24h": "7d", "7d": "30d", "30d": "30d" };
  const larger = largerByPeriod[period] || "24h";

  const buyNow = Math.max(0, sumPressure(topItems, period, "buy"));
  const sellNow = Math.max(0, sumPressure([...shockItems, ...overheatItems], period, "sell"));
  const buyRef = Math.max(0, sumPressure(topItems, larger, "buy"));
  const sellRef = Math.max(0, sumPressure([...shockItems, ...overheatItems], larger, "sell"));
  const buyTrend = (buyNow - buyRef) * 0.10;
  const sellTrend = (sellNow - sellRef) * 0.10;

  const formatAgo = (sec) => {
    if (sec >= 86400) return `-${Math.round(sec / 86400)}д`;
    if (sec >= 3600) return `-${Math.round(sec / 3600)}ч`;
    return `-${Math.max(1, Math.round(sec / 60))}м`;
  };
  const fractions = [1, 0.75, 0.5, 0.25, 0];
  const anchors = fractions.map((f, idx) => {
    const backSec = Math.round(periodSec * f);
    const label = idx === fractions.length - 1 ? "Сейчас" : formatAgo(backSec);
    return {
      label,
      buy: Math.max(0, buyNow - buyTrend * (fractions.length - 1 - idx)),
      sell: Math.max(0, sellNow - sellTrend * (fractions.length - 1 - idx)),
    };
  });
  const maxAbs = Math.max(
    1,
    ...anchors.map((p) => Math.max(Math.abs(Number(p.buy || 0)), Math.abs(Number(p.sell || 0))))
  );
  const normalized = anchors.map((p) => ({
    label: p.label,
    buy: (Number(p.buy || 0) / maxAbs) * 100,
    sell: (Number(p.sell || 0) / maxAbs) * 100,
  }));
  return interpolateAnchors(normalized, 8);
}

function renderOverviewSignalChart(points) {
  const svg = el.overviewSignalChart;
  if (!svg) return;
  if (!points?.length) {
    svg.innerHTML = "";
    return;
  }
  const { width, height } = chartDims(svg, 900, 300);
  const pad = { l: 62, r: 18, t: 16, b: 42 };
  const innerW = width - pad.l - pad.r;
  const innerH = height - pad.t - pad.b;
  const safe = points
    .map((p) => ({
      ...p,
      buy: Math.max(0, Number(p?.buy || 0)),
      sell: Math.max(0, Number(p?.sell || 0)),
    }))
    .filter((p) => Number.isFinite(p.buy) && Number.isFinite(p.sell));
  if (!safe.length) {
    svg.innerHTML = "";
    return;
  }
  const maxY = Math.max(1, ...safe.map((p) => Math.max(p.buy, p.sell)));
  const stepX = innerW / Math.max(safe.length - 1, 1);
  const mapX = (i) => pad.l + i * stepX;
  const mapY = (v) => pad.t + innerH - (Number(v || 0) / maxY) * innerH;

  const pathFromKey = (key) => smoothLinePath(
    safe.map((p) => ({ value_ton: p[key] })),
    mapX,
    mapY,
  );

  const buyPath = pathFromKey("buy");
  const sellPath = pathFromKey("sell");
  const buyArea = `${buyPath} L ${mapX(safe.length - 1).toFixed(2)} ${(height - pad.b).toFixed(2)} L ${mapX(0).toFixed(2)} ${(height - pad.b).toFixed(2)} Z`;
  const sellArea = `${sellPath} L ${mapX(safe.length - 1).toFixed(2)} ${(height - pad.b).toFixed(2)} L ${mapX(0).toFixed(2)} ${(height - pad.b).toFixed(2)} Z`;
  const grid = [0, 0.25, 0.5, 0.75, 1]
    .map((t) => {
      const y = pad.t + innerH * t;
      const v = maxY - maxY * t;
      return `
        <line x1="${pad.l}" y1="${y}" x2="${width - pad.r}" y2="${y}" stroke="#dbe4d8" stroke-width="1" />
        <text x="${pad.l - 8}" y="${y + 4}" text-anchor="end" fill="#5f6874" font-size="11">${v.toFixed(0)}</text>
      `;
    })
    .join("");
  const xTickCount = Math.min(5, Math.max(2, safe.length));
  const xTicks = Array.from({ length: xTickCount }, (_, i) => {
    const idx = Math.round((i / (xTickCount - 1)) * (safe.length - 1));
    const x = mapX(idx);
    const label = String(safe[idx]?.label || "");
    return `
      <line x1="${x}" y1="${pad.t}" x2="${x}" y2="${height - pad.b}" stroke="#edf2ee" stroke-width="1" />
      <text x="${x}" y="${height - 10}" text-anchor="middle" fill="#5f6874" font-size="11">${label}</text>
    `;
  }).join("");

  svg.innerHTML = `
    <rect x="0" y="0" width="${width}" height="${height}" fill="transparent"></rect>
    ${xTicks}
    ${grid}
    <line x1="${pad.l}" y1="${pad.t}" x2="${pad.l}" y2="${height - pad.b}" stroke="#9fb3a8" stroke-width="1.2" />
    <line x1="${pad.l}" y1="${height - pad.b}" x2="${width - pad.r}" y2="${height - pad.b}" stroke="#9fb3a8" stroke-width="1.2" />
    <path d="${buyArea}" fill="rgba(21,128,61,0.12)"></path>
    <path d="${sellArea}" fill="rgba(185,28,28,0.10)"></path>
    <path d="${buyPath}" fill="none" stroke="#15803d" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"></path>
    <path d="${sellPath}" fill="none" stroke="#b91c1c" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"></path>
    <text x="${pad.l}" y="${pad.t - 4}" fill="#5f6874" font-size="11">Индекс</text>
  `;
}

function bindOverviewSignalTooltip() {
  if (!el.overviewSignalChart || !el.overviewSignalTooltip) return;
  el.overviewSignalChart.addEventListener("mousemove", (e) => {
    const points = state.overviewSignal.points || [];
    if (!points.length) return;
    const rect = el.overviewSignalChart.getBoundingClientRect();
    const x = Math.max(0, Math.min(rect.width, e.clientX - rect.left));
    const idx = Math.max(0, Math.min(points.length - 1, Math.round((x / Math.max(rect.width, 1)) * (points.length - 1))));
    const p = points[idx];
    el.overviewSignalTooltip.textContent = `${p.label} • Покупки ${Number(p.buy || 0).toFixed(1)} • Продажи ${Number(p.sell || 0).toFixed(1)}`;
    el.overviewSignalTooltip.style.left = `${x}px`;
    el.overviewSignalTooltip.style.top = `${e.clientY - rect.top}px`;
    el.overviewSignalTooltip.classList.remove("hidden");
  });
  el.overviewSignalChart.addEventListener("mouseleave", () => {
    el.overviewSignalTooltip.classList.add("hidden");
  });
}

function buildRecoPool(topItems = [], shockItems = [], overheatItems = []) {
  const merged = [...topItems, ...shockItems, ...overheatItems];
  const uniq = new Map();
  for (const item of merged) {
    const id = item?.variant_id;
    if (!id || uniq.has(id)) continue;
    uniq.set(id, item);
  }
  return [...uniq.values()].sort((a, b) => Number(b?.reco?.reco_score || 0) - Number(a?.reco?.reco_score || 0));
}

function renderRecoDaySet() {
  const pool = state.recoDay.pool || [];
  if (!pool.length) {
    el.recoDayBody.innerHTML = `<div class="empty-state">Нет рекомендации дня</div>`;
    return;
  }
  const count = Math.min(3, pool.length);
  const offset = state.recoDay.offset % pool.length;
  const picks = [];
  for (let i = 0; i < count; i += 1) {
    picks.push(pool[(offset + i) % pool.length]);
  }
  el.recoDayBody.innerHTML = `<div class="stack">${
    picks
      .map((best) => {
        const icon = renderGiftIcon(best.preview_url, best.title || best.variant_id, "gift-icon-sm");
        return `<div class="table-row">
          <button class="btn ghost open-variant gift-cell" data-variant="${best.variant_id}">${icon}<span>${best.title || best.variant_id}</span></button>
          <span class="chip ${(best.reco?.action || "hold").toLowerCase()}">${actionLabel(best.reco?.action || "HOLD")}</span>
          <span>${formatTon(best.metrics?.floor_ton)} TON</span>
        </div>`;
      })
      .join("")
  }</div>`;
}

function renderMarketAiSignal() {
  const items = state.marketAiSignal.items || [];
  if (!items.length) {
    el.marketAiSignalBody.innerHTML = `<div class="empty-state">Нет данных</div>`;
    return;
  }
  const rec = items[0] || {};
  const actionText = actionLabel(rec.action || "HOLD");
  const scoreText = Number(rec.reco_score ?? 0).toFixed(1);
  const confidenceText = `${Math.round(Number(rec.confidence ?? 0))}%`;
  const fc = rec.forecast || {};
  const range = Array.isArray(fc.range_pct) ? fc.range_pct : [];
  const low = range.length >= 2 ? Number(range[0]).toFixed(1) : "-";
  const high = range.length >= 2 ? Number(range[1]).toFixed(1) : "-";
  const fcBiasMap = { up: "рост", down: "снижение", flat: "боковик" };
  const fcBias = fcBiasMap[fc.bias] || "боковик";
  const risks = Array.isArray(rec.risks) ? rec.risks : [];
  const riskTexts = [];
  for (const r of risks) {
    const text = String(r?.text || r?.title || "").trim();
    if (!text) continue;
    if (riskTexts.includes(text)) continue;
    riskTexts.push(text);
  }
  const risksPart = riskTexts.length ? ` Риски: ${riskTexts.join(" | ")}` : "";
  const line = `${actionText} • Оценка: ${scoreText} • Уверенность: ${confidenceText}, ожидается ${fcBias} (24ч: ${low}%…${high}%, оценка ${scoreText}, уверенность ${confidenceText})${risksPart}`;
  el.marketAiSignalBody.innerHTML = `
    <div class="stack reco-stack">
      <div class="reco-row"><strong>${line}</strong></div>
    </div>
  `;
}

async function refreshMarketAiSignal(force = false) {
  const now = Date.now();
  const mustRefresh =
    force
    || !state.marketAiSignal.lastFetchTs
    || (now - state.marketAiSignal.lastFetchTs >= state.marketAiSignal.refreshMs);
  if (!mustRefresh) {
    renderMarketAiSignal();
    return;
  }
  try {
    const rec = await fetchJson("/api/recommendations?scope=all&entity=variant&ai=1");
    state.marketAiSignal.items = rec.items || [];
    state.marketAiSignal.lastFetchTs = now;
  } catch (e) {
    // keep last successful payload
  }
  renderMarketAiSignal();
}

function startRecoRotation() {
  if (state.recoDay.timer) {
    clearInterval(state.recoDay.timer);
    state.recoDay.timer = null;
  }
  if ((state.recoDay.pool || []).length <= 1) return;
  state.recoDay.timer = setInterval(() => {
    state.recoDay.offset = (state.recoDay.offset + 1) % state.recoDay.pool.length;
    renderRecoDaySet();
  }, 15000);
}

function renderBases() {
  const query = (el.baseSearch.value || "").trim().toLowerCase();
  const filtered = state.bases.filter((b) => {
    if (!query) return true;
    return b.name.toLowerCase().includes(query) || b.base_id.toLowerCase().includes(query);
  });

  el.baseFilterChips.innerHTML = query ? `<span class="chip">поиск: ${query}</span>` : "";

  if (!filtered.length) {
    el.basesBody.innerHTML = `<tr><td colspan="7"><div class="empty-state">Нет коллекций по текущему фильтру</div></td></tr>`;
    return;
  }

  el.basesBody.innerHTML = filtered
    .map((b) => {
      const floor = b.metrics?.floor_ton;
      const floorStars = b.metrics?.floor_stars_est || starsFromTon(floor);
      const delta1h = metricDelta(b.metrics, "1h");
      const delta12h = metricDelta(b.metrics, "12h");
      const delta = metricDelta(b.metrics, "24h");
      const icon = renderGiftIcon(b.preview_url, b.name, "gift-icon-sm");
      return `<tr>
        <td><button class="btn ghost open-base gift-cell" data-base="${b.base_id}">${icon}<span>${b.name}</span></button></td>
        <td>${formatTon(floor)}</td>
        <td>${formatStars(floorStars)}</td>
        <td style="${percentClass(delta1h)}">${formatPct(delta1h)}</td>
        <td style="${percentClass(delta12h)}">${formatPct(delta12h)}</td>
        <td style="${percentClass(delta)}">${formatPct(delta)}</td>
        <td>${b.metrics?.active_listings ?? 0}</td>
      </tr>`;
    })
    .join("");
}

function fillSelect(selectEl, items, valueKey = "id", labelKey = "name", emptyLabel = "Все") {
  const options = [`<option value="">${emptyLabel}</option>`];
  for (const item of items || []) {
    const value = item?.[valueKey] ?? "";
    const label = item?.[labelKey] ?? value;
    if (!value) continue;
    options.push(`<option value="${value}">${label}</option>`);
  }
  selectEl.innerHTML = options.join("");
  syncCustomSelect(selectEl);
}

function fillMultiSelect(selectEl, items, valueKey = "id", labelKey = "name") {
  const options = [];
  for (const item of items || []) {
    const value = item?.[valueKey] ?? "";
    const label = item?.[labelKey] ?? value;
    if (!value) continue;
    options.push(`<option value="${value}">${label}</option>`);
  }
  selectEl.innerHTML = options.join("");
  syncCustomSelect(selectEl);
}

function selectedValues(selectEl) {
  return [...(selectEl?.selectedOptions || [])].map((o) => o.value).filter(Boolean);
}

function closeCustomSelect(state) {
  if (!state?.root || !state?.menu || !state?.trigger) return;
  state.root.classList.remove("open");
  state.menu.classList.add("hidden");
  state.trigger.setAttribute("aria-expanded", "false");
}

function closeAllCustomSelects(exceptSelect = null) {
  for (const [selectEl, state] of customSelectRegistry.entries()) {
    if (exceptSelect && selectEl === exceptSelect) continue;
    closeCustomSelect(state);
  }
}

function destroyCustomSelect(selectEl) {
  const state = customSelectRegistry.get(selectEl);
  if (state?.root?.parentElement) {
    state.root.parentElement.removeChild(state.root);
  }
  customSelectRegistry.delete(selectEl);
  if (selectEl) {
    selectEl.classList.remove("native-select-hidden");
    selectEl.tabIndex = 0;
  }
}

function renderCustomSelectOptions(selectEl) {
  const state = customSelectRegistry.get(selectEl);
  if (!state || !state.menu || !selectEl) return;
  const options = [...selectEl.options];
  const isMultiple = Boolean(selectEl.multiple);
  state.menu.innerHTML = options
    .map((opt) => {
      const value = String(opt.value || "");
      const selected = isMultiple ? Boolean(opt.selected) : value === String(selectEl.value || "");
      return `<button type="button" class="custom-select-option ${selected ? "active" : ""}" data-value="${escapeHtml(value)}" data-selected="${selected ? "1" : "0"}">${escapeHtml(opt.textContent || "")}</button>`;
    })
    .join("");
}

function syncCustomSelect(selectEl) {
  const state = customSelectRegistry.get(selectEl);
  if (!state || !state.trigger || !selectEl) return;
  if (selectEl.multiple) {
    const values = [...(selectEl.selectedOptions || [])].map((x) => String(x.textContent || "").trim()).filter(Boolean);
    if (!values.length) {
      state.trigger.textContent = "Выберите значения";
    } else if (values.length <= 2) {
      state.trigger.textContent = values.join(", ");
    } else {
      state.trigger.textContent = `Выбрано: ${values.length}`;
    }
  } else {
    const selected = selectEl.selectedOptions?.[0];
    state.trigger.textContent = selected?.textContent || "Выберите значение";
  }
  renderCustomSelectOptions(selectEl);
}

function initCustomSelect(selectEl) {
  if (!selectEl) return;
  const parent = selectEl.parentElement;
  if (!parent) return;

  const existing = customSelectRegistry.get(selectEl);
  if (existing?.root && document.body.contains(existing.root) && existing.root.parentElement === parent) {
    // Keep a single stable custom-select instance per native select.
    for (const node of [...parent.children]) {
      if (!node.classList?.contains("custom-select")) continue;
      if (node !== existing.root) node.remove();
    }
    syncCustomSelect(selectEl);
    return;
  }
  if (existing) {
    destroyCustomSelect(selectEl);
  }

  // Defensive dedupe: remove stale roots before creating the current one.
  for (const node of [...parent.children]) {
    if (node.classList?.contains("custom-select")) {
      node.remove();
    }
  }

  if (customSelectRegistry.has(selectEl)) {
    return;
  }

  const root = document.createElement("div");
  const isMultiple = Boolean(selectEl.multiple);
  root.className = `custom-select${isMultiple ? " multiple" : ""}`;
  root.innerHTML = `
    <button type="button" class="custom-select-trigger" aria-haspopup="listbox" aria-expanded="false">${isMultiple ? "Выберите значения" : "Выберите значение"}</button>
    <div class="custom-select-menu hidden" role="listbox"></div>
  `;
  parent.appendChild(root);

  const state = {
    root,
    trigger: root.querySelector(".custom-select-trigger"),
    menu: root.querySelector(".custom-select-menu"),
  };
  customSelectRegistry.set(selectEl, state);

  selectEl.classList.add("native-select-hidden");
  selectEl.tabIndex = -1;

  state.trigger.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    const willOpen = !state.root.classList.contains("open");
    closeAllCustomSelects(selectEl);
    state.root.classList.toggle("open", willOpen);
    state.menu.classList.toggle("hidden", !willOpen);
    state.trigger.setAttribute("aria-expanded", willOpen ? "true" : "false");
  });

  state.menu.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    const optionBtn = e.target.closest(".custom-select-option");
    if (!optionBtn) return;
    const value = optionBtn.dataset.value ?? "";
    if (selectEl.multiple) {
      let changed = false;
      for (const opt of selectEl.options) {
        if (String(opt.value) !== String(value)) continue;
        opt.selected = !opt.selected;
        changed = true;
        break;
      }
      if (changed) {
        selectEl.dispatchEvent(new Event("change", { bubbles: true }));
      }
      syncCustomSelect(selectEl);
      return;
    }
    // Close first to avoid visual flicker/secondary open while change listeners rerender options.
    closeCustomSelect(state);
    if (selectEl.value !== value) {
      selectEl.value = value;
      selectEl.dispatchEvent(new Event("change", { bubbles: true }));
    }
    syncCustomSelect(selectEl);
  });

  syncCustomSelect(selectEl);
}

function initAllCustomSelects() {
  // Clean registry entries for detached selects to avoid duplicated UI instances.
  for (const [selectEl] of customSelectRegistry.entries()) {
    if (!document.body.contains(selectEl)) {
      customSelectRegistry.delete(selectEl);
    }
  }
  const all = [...document.querySelectorAll("select")];
  for (const selectEl of all) {
    initCustomSelect(selectEl);
  }
}

function renderCatalogVariants(items) {
  if (!items.length) {
    el.catalogVariantsBody.innerHTML = `<tr><td colspan="7"><div class="empty-state">Нет вариантов по фильтрам</div></td></tr>`;
    return;
  }
  el.catalogVariantsBody.innerHTML = items
    .map((v) => {
      const variantLabel = v?.traits?.model?.name && v?.traits?.background?.name && v?.traits?.pattern?.name
        ? `${v.traits.model.name} • ${v.traits.background.name} • ${v.traits.pattern.name}`
        : (v.title || v.variant_id);
      const floor = v.metrics?.floor_ton;
      const stars = v.metrics?.floor_stars_est || starsFromTon(floor);
      const delta1h = metricDelta(v.metrics, "1h");
      const delta12h = metricDelta(v.metrics, "12h");
      const delta = metricDelta(v.metrics, "24h");
      const icon = renderGiftIcon(v.preview_url, variantLabel, "gift-icon-sm");
      return `<tr>
        <td><button class="btn ghost open-variant gift-cell" data-variant="${v.variant_id}">${icon}<span>${variantLabel}</span></button></td>
        <td>${formatTon(floor)}</td>
        <td>${formatStars(stars)}</td>
        <td style="${percentClass(delta1h)}">${formatPct(delta1h)}</td>
        <td style="${percentClass(delta12h)}">${formatPct(delta12h)}</td>
        <td style="${percentClass(delta)}">${formatPct(delta)}</td>
        <td><span class="chip ${(v.reco?.action || "hold").toLowerCase()}">${actionLabel(v.reco?.action || "HOLD")}</span></td>
      </tr>`;
    })
    .join("");
}

async function loadCatalogFiltersAndVariants() {
  closeAllCustomSelects();
  const baseId = state.catalogFilters.baseId || state.bases[0]?.base_id || "";
  if (!baseId) {
    el.catalogVariantsBody.innerHTML = `<tr><td colspan="7"><div class="empty-state">Нет данных</div></td></tr>`;
    return;
  }
  state.catalogFilters.baseId = baseId;
  if (el.catalogBaseSelect.value !== baseId) el.catalogBaseSelect.value = baseId;
  syncCustomSelect(el.catalogBaseSelect);

  const [modelsResp, backgroundsResp, patternsResp] = await Promise.all([
    fetchJson(`/api/bases/${baseId}/dimensions?type=model&period=24h`),
    fetchJson(`/api/bases/${baseId}/dimensions?type=background&period=24h`),
    fetchJson(`/api/bases/${baseId}/dimensions?type=pattern&period=24h`),
  ]);
  const models = (modelsResp.items || []).map((x) => ({ id: x.dim_id, name: x.name }));
  const backgrounds = (backgroundsResp.items || []).map((x) => ({ id: x.dim_id, name: x.name }));
  const patterns = (patternsResp.items || []).map((x) => ({ id: x.dim_id, name: x.name }));
  fillSelect(el.catalogModelSelect, models, "id", "name", "Все модели");
  fillMultiSelect(el.catalogBackgroundSelect, backgrounds, "id", "name");
  fillMultiSelect(el.catalogPatternSelect, patterns, "id", "name");
  el.catalogModelSelect.value = state.catalogFilters.modelId || "";
  syncCustomSelect(el.catalogModelSelect);
  for (const opt of el.catalogBackgroundSelect.options) {
    opt.selected = state.catalogFilters.backgroundIds.includes(opt.value);
  }
  syncCustomSelect(el.catalogBackgroundSelect);
  for (const opt of el.catalogPatternSelect.options) {
    opt.selected = state.catalogFilters.patternIds.includes(opt.value);
  }
  syncCustomSelect(el.catalogPatternSelect);

  const params = new URLSearchParams({ page: "1", page_size: "300" });
  if (state.catalogFilters.modelId) params.append("model_id", state.catalogFilters.modelId);
  for (const bg of state.catalogFilters.backgroundIds) params.append("background_id", bg);
  for (const p of state.catalogFilters.patternIds) params.append("pattern_id", p);
  const variantsResp = await fetchJson(`/api/bases/${baseId}/variants?${params.toString()}`);
  renderCatalogVariants(variantsResp.items || []);
}

function renderScreeners(items) {
  if (!items.length) {
    el.screenersBody.innerHTML = `<tr><td colspan="7"><div class="empty-state">Скринер пуст</div></td></tr>`;
    return;
  }
  el.screenersBody.innerHTML = items
    .map((v) => {
      const floor = v.metrics?.floor_ton;
      const stars = v.metrics?.floor_stars_est || starsFromTon(floor);
      const delta1h = metricDelta(v.metrics, "1h");
      const delta12h = metricDelta(v.metrics, "12h");
      const delta = metricDelta(v.metrics, "24h");
      const icon = renderGiftIcon(v.preview_url, v.title || v.variant_id, "gift-icon-sm");
      return `<tr>
        <td><button class="btn ghost open-variant gift-cell" data-variant="${v.variant_id}">${icon}<span>${v.title || v.variant_id}</span></button></td>
        <td>${formatTon(floor)}</td>
        <td>${formatStars(stars)}</td>
        <td style="${percentClass(delta1h)}">${formatPct(delta1h)}</td>
        <td style="${percentClass(delta12h)}">${formatPct(delta12h)}</td>
        <td style="${percentClass(delta)}">${formatPct(delta)}</td>
        <td><span class="chip ${(v.reco?.action || "hold").toLowerCase()}">${actionLabel(v.reco?.action || "HOLD")}</span></td>
      </tr>`;
    })
    .join("");
}

function collectSignalItems() {
  const items = Array.isArray(state.signals.items) ? state.signals.items : [];
  return items.slice().sort((a, b) => Number(b?.reco?.reco_score || 0) - Number(a?.reco?.reco_score || 0));
}

function renderSignals() {
  if (!el.signalsBody || !el.signalsStats) return;
  const allSignals = collectSignalItems();
  const buyCount = Number(state.signals.buyTotal || 0);
  const sellCount = Number(state.signals.sellTotal || 0);
  const activeFilter = state.signals.filter || "all";
  const filtered = allSignals.filter((v) => {
    const action = String(v?.reco?.action || "").toUpperCase();
    if (activeFilter === "buy") return action === "BUY";
    if (activeFilter === "sell") return action === "SELL";
    return true;
  });

  el.signalsStats.innerHTML = [
    ["Сигналов", buyCount + sellCount],
    ["BUY", buyCount],
    ["SELL", sellCount],
    ["Показано", filtered.length],
  ].map(([k, v]) => `<div class="kpi-item"><div class="kpi-key">${k}</div><div class="kpi-value">${v}</div></div>`).join("");

  if (!filtered.length) {
    const label = activeFilter === "buy" ? "BUY" : activeFilter === "sell" ? "SELL" : "BUY/SELL";
    el.signalsBody.innerHTML = `<tr><td colspan="7"><div class="empty-state">Сигналы ${label} не найдены</div></td></tr>`;
    return;
  }

  el.signalsBody.innerHTML = filtered
    .map((v) => {
      const action = String(v?.reco?.action || "HOLD").toUpperCase();
      const floor = Number(v?.metrics?.floor_ton || 0);
      const stars = Number(v?.metrics?.floor_stars_est || starsFromTon(floor) || 0);
      const delta1h = metricDelta(v?.metrics, "1h");
      const delta12h = metricDelta(v?.metrics, "12h");
      const delta24h = metricDelta(v?.metrics, "24h");
      const variantLabel = v?.traits?.model?.name && v?.traits?.background?.name && v?.traits?.pattern?.name
        ? `${v.traits.model.name} • ${v.traits.background.name} • ${v.traits.pattern.name}`
        : (v.title || v.variant_id);
      const icon = renderGiftIcon(v.preview_url, variantLabel, "gift-icon-sm");
      return `<tr>
        <td><button class="btn ghost open-variant gift-cell" data-variant="${v.variant_id}">${icon}<span>${variantLabel}</span></button></td>
        <td>${formatTon(floor)}</td>
        <td>${formatStars(stars)}</td>
        <td style="${percentClass(delta1h)}">${formatPct(delta1h)}</td>
        <td style="${percentClass(delta12h)}">${formatPct(delta12h)}</td>
        <td style="${percentClass(delta24h)}">${formatPct(delta24h)}</td>
        <td><span class="chip ${(action || "hold").toLowerCase()}">${actionLabel(action)}</span></td>
      </tr>`;
    })
    .join("");
}

function setSignalFilter(filter) {
  state.signals.filter = filter || "all";
  const buttons = [el.signalFilterAll, el.signalFilterBuy, el.signalFilterSell];
  for (const btn of buttons) {
    if (!btn) continue;
    btn.classList.toggle("active", btn.dataset.filter === state.signals.filter);
  }
  loadSignalsPage().catch(() => {
    renderSignals();
  });
}

function renderWatchlist() {
  const items = state.variants.filter((v) => state.watchlist.has(v.variant_id));
  if (!items.length) {
    el.watchlistBody.innerHTML = `<tr><td colspan="4"><div class="empty-state">Избранное пусто</div></td></tr>`;
    return;
  }
  el.watchlistBody.innerHTML = items
    .map((v) => {
      const reco = v.reco || {};
      const icon = renderGiftIcon(v.preview_url, v.variant_id, "gift-icon-sm");
      return `<tr>
        <td><button class="btn ghost open-variant gift-cell" data-variant="${v.variant_id}">${icon}<span>${v.variant_id}</span></button></td>
        <td>${formatTon(v.metrics?.floor_ton)}</td>
        <td><span class="chip ${(reco.action || "hold").toLowerCase()}">${actionLabel(reco.action || "HOLD")}</span></td>
        <td><button class="btn ghost toggle-watch" data-variant="${v.variant_id}">Убрать</button></td>
      </tr>`;
    })
    .join("");
}

function renderBaseDetails(base, variants) {
  if (!base) {
    el.baseTitle.textContent = "Коллекция не найдена";
    el.baseVariantsBody.innerHTML = `<tr><td colspan="7"><div class="empty-state">Нет данных</div></td></tr>`;
    return;
  }
  const m = base.metrics || {};
  el.baseTitle.textContent = base.name || base.base_id;
  el.baseFloor.textContent = `${formatTon(m.floor_ton)} TON`;
  el.baseListings.textContent = `${m.active_listings ?? 0}`;
  el.baseMeta.textContent = `ID: ${base.base_id} • Вариантов: ${variants.length}`;

  if (!variants.length) {
    el.baseVariantsBody.innerHTML = `<tr><td colspan="7"><div class="empty-state">По коллекции нет активных вариантов</div></td></tr>`;
    return;
  }
  el.baseVariantsBody.innerHTML = variants
    .map((v) => {
      const floor = v.metrics?.floor_ton;
      const stars = v.metrics?.floor_stars_est || starsFromTon(floor);
      const delta1h = metricDelta(v.metrics, "1h");
      const delta12h = metricDelta(v.metrics, "12h");
      const delta = metricDelta(v.metrics, "24h");
      const icon = renderGiftIcon(v.preview_url, v.title || v.variant_id, "gift-icon-sm");
      return `<tr>
        <td><button class="btn ghost open-variant gift-cell" data-variant="${v.variant_id}">${icon}<span>${v.title || v.variant_id}</span></button></td>
        <td>${formatTon(floor)}</td>
        <td>${formatStars(stars)}</td>
        <td style="${percentClass(delta1h)}">${formatPct(delta1h)}</td>
        <td style="${percentClass(delta12h)}">${formatPct(delta12h)}</td>
        <td style="${percentClass(delta)}">${formatPct(delta)}</td>
        <td><span class="chip ${(v.reco?.action || "hold").toLowerCase()}">${actionLabel(v.reco?.action || "HOLD")}</span></td>
      </tr>`;
    })
    .join("");
}

function sortedListingsRows() {
  const rows = [...state.listings.rows];
  const { sortField, sortDir } = state.listings;
  rows.sort((a, b) => {
    const av = a?.[sortField];
    const bv = b?.[sortField];
    if (sortField === "price_ton") {
      return (Number(av || 0) - Number(bv || 0)) * (sortDir === "asc" ? 1 : -1);
    }
    return String(av || "").localeCompare(String(bv || "")) * (sortDir === "asc" ? 1 : -1);
  });
  return rows;
}

function renderVariantListings() {
  const rows = sortedListingsRows();
  if (!rows.length) {
    el.variantListingsBody.innerHTML = `<tr><td colspan="5"><div class="empty-state">Активные лоты не найдены</div></td></tr>`;
    return;
  }
  el.variantListingsBody.innerHTML = rows
    .map((l) => `<tr>
      <td>${l.listing_id}</td>
      <td>${saleTypeLabel(l.sale_type)}</td>
      <td>${statusLabel(l.status)}</td>
      <td>${formatTon(l.price_ton)}</td>
      <td>${formatStars(l.price_stars_est || starsFromTon(l.price_ton))}</td>
    </tr>`)
    .join("");
}

function periodSeconds(period) {
  const map = {
    "1h": 3600,
    "12h": 12 * 3600,
    "24h": 24 * 3600,
    "7d": 7 * 24 * 3600,
    "30d": 30 * 24 * 3600,
  };
  return map[String(period || "24h")] || map["24h"];
}

function denseCurveFromAnchors(anchors, startMs, endMs, targetPoints) {
  const safeAnchors = (anchors || [])
    .filter((p) => Number.isFinite(Number(p?.tsMs)) && Number.isFinite(Number(p?.value)))
    .map((p) => ({ tsMs: Number(p.tsMs), value: Number(p.value) }))
    .sort((a, b) => a.tsMs - b.tsMs);
  if (!safeAnchors.length || endMs <= startMs) return [];

  const first = safeAnchors[0];
  const last = safeAnchors[safeAnchors.length - 1];
  const normalized = [...safeAnchors];
  if (first.tsMs > startMs) normalized.unshift({ tsMs: startMs, value: first.value });
  if (last.tsMs < endMs) normalized.push({ tsMs: endMs, value: last.value });

  const count = Math.max(18, Number(targetPoints || 48));
  let seg = 0;
  const out = [];
  for (let i = 0; i < count; i += 1) {
    const t = startMs + ((endMs - startMs) * i) / Math.max(count - 1, 1);
    while (seg < normalized.length - 2 && t > normalized[seg + 1].tsMs) seg += 1;
    const a = normalized[seg];
    const b = normalized[Math.min(seg + 1, normalized.length - 1)];
    const dt = Math.max(1, b.tsMs - a.tsMs);
    const k = Math.max(0, Math.min(1, (t - a.tsMs) / dt));
    const v = a.value + (b.value - a.value) * k;
    out.push({
      ts: new Date(t).toISOString(),
      value_ton: v,
    });
  }
  return out;
}

function estimateHistoricalFromPct(currentFloor, pct) {
  const current = Number(currentFloor);
  const change = Number(pct);
  if (!Number.isFinite(current) || current <= 0 || !Number.isFinite(change)) return null;
  const denom = 1 + change / 100;
  if (!Number.isFinite(denom) || Math.abs(denom) < 1e-6) return null;
  const prev = current / denom;
  return Number.isFinite(prev) && prev > 0 ? prev : null;
}

function syntheticVariantAnchors(variant, period) {
  const metrics = variant?.metrics || {};
  const nowMs = Date.now();
  const windowSec = periodSeconds(period);
  const current = Number(metrics.floor_ton);
  if (!Number.isFinite(current) || current <= 0) return [];

  const checkpoints = [
    { sec: 30 * 24 * 3600, key: "floor_change_pct_30d" },
    { sec: 7 * 24 * 3600, key: "floor_change_pct_7d" },
    { sec: 24 * 3600, key: "floor_change_pct_24h" },
    { sec: 12 * 3600, key: "floor_change_pct_12h" },
    { sec: 3600, key: "floor_change_pct_1h" },
  ];

  const anchors = [{ tsMs: nowMs, value: current }];
  for (const cp of checkpoints) {
    if (cp.sec > windowSec) continue;
    const val = estimateHistoricalFromPct(current, metrics?.[cp.key]);
    if (!Number.isFinite(val) || val <= 0) continue;
    anchors.push({ tsMs: nowMs - cp.sec * 1000, value: val });
  }
  return anchors.sort((a, b) => a.tsMs - b.tsMs);
}

function currentVariantForChart() {
  return state.variants.find((v) => v.variant_id === state.selectedVariantId) || null;
}

function resolveVariantChartPoints(rawPoints, variant, period) {
  const windowSec = periodSeconds(period);
  const nowMs = Date.now();
  const startMs = nowMs - windowSec * 1000;

  const rawAnchors = (rawPoints || [])
    .map((p) => {
      const tsMs = new Date(String(p?.ts || "")).getTime();
      const value = Number(p?.value_ton);
      if (!Number.isFinite(tsMs) || !Number.isFinite(value) || value <= 0) return null;
      return { tsMs, value };
    })
    .filter(Boolean)
    .sort((a, b) => a.tsMs - b.tsMs);

  if (rawAnchors.length >= 6) {
    return denseCurveFromAnchors(rawAnchors, startMs, nowMs, Math.min(200, Math.max(48, rawAnchors.length * 3)));
  }

  const syntheticAnchors = syntheticVariantAnchors(variant, period);
  const mergedByTs = new Map();
  for (const a of syntheticAnchors) mergedByTs.set(Math.round(a.tsMs / 1000), a);
  for (const a of rawAnchors) mergedByTs.set(Math.round(a.tsMs / 1000), a);
  const merged = [...mergedByTs.values()].sort((a, b) => a.tsMs - b.tsMs);
  if (!merged.length) return [];

  const target = windowSec <= 12 * 3600 ? 72 : windowSec <= 24 * 3600 ? 96 : windowSec <= 7 * 24 * 3600 ? 120 : 160;
  return denseCurveFromAnchors(merged, startMs, nowMs, target);
}

function getVisibleChartPoints() {
  const rawPoints = state.chart.points || [];
  if (!rawPoints.length) return [];
  const points = rawPoints
    .map((p) => {
      const value = Number(p?.value_ton);
      if (!Number.isFinite(value)) return null;
      return { ...p, value_ton: value };
    })
    .filter(Boolean);
  if (!points.length) return [];
  const len = points.length;
  const from = Math.max(0, Math.floor(state.chart.start * (len - 1)));
  const to = Math.min(len - 1, Math.ceil(state.chart.end * (len - 1)));
  return points.slice(from, to + 1);
}

function chartDims(svg, fallbackW = 900, fallbackH = 320) {
  const vb = String(svg?.getAttribute("viewBox") || "").trim().split(/\s+/);
  if (vb.length === 4) {
    const w = Number(vb[2] || 0);
    const h = Number(vb[3] || 0);
    if (w > 0 && h > 0) return { width: w, height: h };
  }
  return { width: fallbackW, height: fallbackH };
}

function formatChartTsLabel(value) {
  const raw = String(value || "").trim();
  if (!raw) return "";
  const d = new Date(raw);
  if (!Number.isNaN(d.getTime())) {
    const fmt = new Intl.DateTimeFormat("ru-RU", {
      timeZone: "Europe/Moscow",
      day: "2-digit",
      month: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    });
    return fmt.format(d).replace(",", "");
  }
  const m = raw.match(/(\d{2}:\d{2})/);
  return m ? m[1] : raw.slice(0, 10);
}

function smoothLinePath(points, mapX, mapY) {
  if (!points.length) return "";
  if (points.length === 1) {
    return `M ${mapX(0).toFixed(2)} ${mapY(Number(points[0].value_ton || 0)).toFixed(2)}`;
  }
  let d = `M ${mapX(0).toFixed(2)} ${mapY(Number(points[0].value_ton || 0)).toFixed(2)}`;
  for (let i = 0; i < points.length - 1; i += 1) {
    const p0 = points[i - 1] || points[i];
    const p1 = points[i];
    const p2 = points[i + 1];
    const p3 = points[i + 2] || p2;
    const x1 = mapX(i);
    const y1 = mapY(Number(p1.value_ton || 0));
    const x2 = mapX(i + 1);
    const y2 = mapY(Number(p2.value_ton || 0));
    const c1x = x1 + (x2 - mapX(Math.max(i - 1, 0))) / 6;
    const c1y = y1 + (y2 - mapY(Number(p0.value_ton || 0))) / 6;
    const c2x = x2 - (mapX(Math.min(i + 2, points.length - 1)) - x1) / 6;
    const c2y = y2 - (mapY(Number(p3.value_ton || 0)) - y1) / 6;
    d += ` C ${c1x.toFixed(2)} ${c1y.toFixed(2)}, ${c2x.toFixed(2)} ${c2y.toFixed(2)}, ${x2.toFixed(2)} ${y2.toFixed(2)}`;
  }
  return d;
}

function renderChart() {
  const svg = el.variantChart;
  const points = getVisibleChartPoints();
  if (!points.length) {
    const { width, height } = chartDims(svg, 1400, 560);
    svg.innerHTML = `
      <rect x="0" y="0" width="${width}" height="${height}" fill="transparent"></rect>
      <text x="${width / 2}" y="${height / 2}" text-anchor="middle" fill="#5f6874" font-size="18">Нет данных для построения графика</text>
    `;
    return;
  }
  const { width, height } = chartDims(svg, 1400, 560);
  // Maximize usable plot area: keep only minimal space for labels.
  const pad = { l: 34, r: 8, t: 0, b: 4 };
  const values = points.map((p) => Number(p.value_ton || 0));
  const min = Math.min(...values);
  const max = Math.max(...values);
  const innerW = width - pad.l - pad.r;
  const innerH = height - pad.t - pad.b;
  const dx = innerW / Math.max(points.length - 1, 1);
  const mapX = (i) => pad.l + i * dx;
  const mapY = (v) => {
    if (max === min) return pad.t + innerH / 2;
    return pad.t + (max - v) * (innerH / (max - min));
  };
  const path = smoothLinePath(points, mapX, mapY);
  const areaPath = `${path} L ${mapX(points.length - 1).toFixed(2)} ${(height - pad.b).toFixed(2)} L ${mapX(0).toFixed(2)} ${(height - pad.b).toFixed(2)} Z`;

  const yTicks = [0, 0.5, 1]
    .map((t) => {
      const y = pad.t + innerH * t;
      const v = max - (max - min) * t;
      return `
        <line x1="${pad.l}" y1="${y}" x2="${width - pad.r}" y2="${y}" stroke="#dbe4d8" stroke-width="1" />
      <text x="4" y="${y + 4}" text-anchor="start" fill="#5f6874" font-size="11">${formatTon(v)}</text>
      `;
    })
    .join("");
  const xTickCount = Math.min(6, Math.max(2, points.length));
  const xTicks = Array.from({ length: xTickCount }, (_, i) => {
    const idx = Math.round((i / (xTickCount - 1)) * (points.length - 1));
    const x = mapX(idx);
    const label = formatChartTsLabel(points[idx]?.ts);
    return `
      <line x1="${x}" y1="${pad.t}" x2="${x}" y2="${height - pad.b}" stroke="#edf2ee" stroke-width="1" />
      <text x="${x}" y="${height - 1}" text-anchor="middle" fill="#5f6874" font-size="10">${label}</text>
    `;
  }).join("");

  svg.innerHTML = `
    <rect x="0" y="0" width="${width}" height="${height}" fill="transparent"></rect>
    ${xTicks}
    ${yTicks}
    <line x1="${pad.l}" y1="${pad.t}" x2="${pad.l}" y2="${height - pad.b}" stroke="#9fb3a8" stroke-width="1.2" />
    <line x1="${pad.l}" y1="${height - pad.b}" x2="${width - pad.r}" y2="${height - pad.b}" stroke="#9fb3a8" stroke-width="1.2" />
    <path d="${areaPath}" fill="rgba(15,118,110,0.14)"></path>
    <path d="${path}" fill="none" stroke="#0f766e" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"></path>
    ${points.length === 1 ? `<circle cx="${mapX(0).toFixed(2)}" cy="${mapY(values[0]).toFixed(2)}" r="6" fill="#0f766e" />` : ""}
    <text x="4" y="9" fill="#5f6874" font-size="10">TON</text>
  `;
}

function chartViewportByPointer(clientX) {
  const rect = el.variantChart.getBoundingClientRect();
  const x = Math.max(0, Math.min(rect.width, clientX - rect.left));
  return rect.width ? x / rect.width : 0.5;
}

function chartZoom(clientX, direction) {
  const points = state.chart.points || [];
  if (points.length < 3) return;
  const anchor = chartViewportByPointer(clientX);
  const range = state.chart.end - state.chart.start;
  const factor = direction > 0 ? 0.86 : 1.14;
  let nextRange = Math.min(1, Math.max(0.08, range * factor));
  const center = state.chart.start + range * anchor;
  let start = center - nextRange * anchor;
  let end = start + nextRange;
  if (start < 0) {
    end -= start;
    start = 0;
  }
  if (end > 1) {
    start -= end - 1;
    end = 1;
  }
  state.chart.start = Math.max(0, start);
  state.chart.end = Math.min(1, end);
  renderChart();
}

function chartPan(deltaPx) {
  const rect = el.variantChart.getBoundingClientRect();
  const span = state.chart.end - state.chart.start;
  if (!rect.width) return;
  const shift = (deltaPx / rect.width) * span;
  let start = state.chart.start - shift;
  let end = state.chart.end - shift;
  if (start < 0) {
    end -= start;
    start = 0;
  }
  if (end > 1) {
    start -= end - 1;
    end = 1;
  }
  state.chart.start = Math.max(0, start);
  state.chart.end = Math.min(1, end);
  renderChart();
}

function showChartTooltip(clientX, clientY) {
  const points = getVisibleChartPoints();
  if (!points.length) return;
  const rect = el.variantChart.getBoundingClientRect();
  const x = Math.max(0, Math.min(rect.width, clientX - rect.left));
  const idx = Math.max(0, Math.min(points.length - 1, Math.round((x / Math.max(rect.width, 1)) * (points.length - 1))));
  const p = points[idx];
  const txt = `${(p.ts || "").replace("T", " ").replace("Z", "")} • ${formatTon(p.value_ton)} TON`;
  el.chartTooltip.textContent = txt;
  el.chartTooltip.style.left = `${x}px`;
  el.chartTooltip.style.top = `${clientY - rect.top}px`;
  el.chartTooltip.classList.remove("hidden");
}

function renderVariantDetails(variant, listings, series) {
  if (!variant) {
    el.variantTitle.textContent = "Вариант не найден";
    return;
  }

  const m = variant.metrics || {};
  const reco = variant.reco || {};
  const model = String(variant.traits?.model?.name || "?").trim();
  const background = String(variant.traits?.background?.name || "?").trim();
  const pattern = String(variant.traits?.pattern?.name || "?").trim();
  const base = state.bases.find((b) => b.base_id === variant.base_id);
  const prettyBaseId = String(variant.base_id || "")
    .replaceAll("_", " ")
    .replaceAll("-", " ")
    .replace(/\s+/g, " ")
    .trim();
  const collection = String(base?.name || variant.base_name || prettyBaseId || variant.base_id || "?").trim();
  const title = `${model} • ${background} • ${pattern}`;
  if (el.variantPreview) {
    if (variant.preview_url) {
      el.variantPreview.src = variant.preview_url;
      el.variantPreview.alt = title;
      el.variantPreview.style.visibility = "visible";
    } else {
      el.variantPreview.removeAttribute("src");
      el.variantPreview.alt = "Изображение недоступно";
      el.variantPreview.style.visibility = "hidden";
    }
  }
  el.variantTitle.innerHTML = `
    <span class="variant-meta-line">Коллекция: <strong>${escapeHtml(collection)}</strong></span>
    <span class="variant-meta-line">Модель: <strong>${escapeHtml(model)}</strong></span>
    <span class="variant-meta-line">Фон: <strong>${escapeHtml(background)}</strong></span>
    <span class="variant-meta-line">Узор: <strong>${escapeHtml(pattern)}</strong></span>
  `;
  el.variantFloor.textContent = `${formatTon(m.floor_ton)} TON (${formatStars(m.floor_stars_est || starsFromTon(m.floor_ton))}⭐)`;
  const deltas = [
    ["1ч", m.floor_change_pct_1h],
    ["12ч", m.floor_change_pct_12h],
    ["24ч", m.floor_change_pct_24h],
  ];
  el.variantDeltaGrid.innerHTML = deltas
    .map(([label, value]) => `<div><span class="muted small">${label}</span><strong style="${percentClass(value || 0)}">${formatPct(value || 0)}</strong></div>`)
    .join("");
  el.variantRecoChip.className = `chip ${(reco.action || "hold").toLowerCase()}`;
  el.variantRecoChip.textContent = `${actionLabel(reco.action || "HOLD")} • ${reco.reco_score ?? 0} • увер. ${reco.confidence ?? 0}`;

  const kpi = [
    ["Цена Δ1ч", formatPct(m.floor_change_pct_1h || 0)],
    ["Цена Δ12ч", formatPct(m.floor_change_pct_12h || 0)],
    ["Цена Δ24ч", formatPct(m.floor_change_pct_24h || 0)],
    ["Активные лоты", m.active_listings],
    ["Сделки 24ч", m.trades_count_24h],
    ["Объем 24ч", `${formatTon(m.volume_ton_24h)} TON`],
    ["Ликвидность", m.liquidity_score_24h ?? "-"],
    ["Волатильность", m.volatility_24h ?? "-"],
  ];
  el.variantKpi.innerHTML = kpi
    .map(([k, v]) => `<div class="kpi-item"><div class="kpi-key">${k}</div><div class="kpi-value">${v}</div></div>`)
    .join("");

  const reasonLabelMap = {
    R_MOMENTUM: "Импульс цены",
    R_SUPPLY_DOWN: "Снижение предложения",
    R_VOLUME: "Объем торгов",
    R_BREAKOUT: "Пробой уровня",
    R_AI: "Сигнал ИИ",
  };
  const riskLabelMap = {
    K_THIN_MARKET: "Тонкий рынок",
    K_VOLATILITY: "Повышенная волатильность",
    K_PUMP_RISK: "Риск перегрева",
    K_DATA_GAPS: "Недостаточно данных",
    K_AI: "Риск по версии ИИ",
  };
  const isAiReason = (code, title) => {
    const c = String(code || "").toUpperCase();
    const t = String(title || "").toLowerCase();
    return c === "R_AI" || c === "K_AI" || t.includes("ии");
  };

  const reasonParts = [];
  let hasAiMention = false;
  const aiReasonTexts = [];
  let aiReasonSlot = -1;
  for (const r of (reco.reasons || [])) {
    const code = String(r.code || "");
    const title = String(r.title || reasonLabelMap[code] || "Фактор");
    const text = String(r.text || "").trim();
    if (isAiReason(code, title)) {
      hasAiMention = true;
      if (aiReasonSlot < 0) {
        aiReasonSlot = reasonParts.length;
        reasonParts.push("");
      }
      aiReasonTexts.push(text || "-");
      continue;
    }
    reasonParts.push(`<strong>${title}:</strong> ${text || "-"}`);
  }
  if (aiReasonSlot >= 0) {
    reasonParts[aiReasonSlot] = `<strong>Сигнал ИИ:</strong> ${aiReasonTexts.join(" | ")}`;
  }

  const riskParts = [];
  const aiRiskTexts = [];
  let aiRiskSlot = -1;
  for (const r of (reco.risks || [])) {
    const code = String(r.code || "");
    const title = String(r.title || riskLabelMap[code] || "Риск");
    const text = String(r.text || "").trim();
    if (isAiReason(code, title)) {
      if (aiRiskSlot < 0) {
        aiRiskSlot = riskParts.length;
        riskParts.push("");
      }
      aiRiskTexts.push(text || "-");
      continue;
    }
    riskParts.push(`<strong>${title}:</strong> ${text || "-"}`);
  }
  if (aiRiskSlot >= 0) {
    riskParts[aiRiskSlot] = `<strong>Сигнал ИИ:</strong> ${aiRiskTexts.join(" | ")}`;
  }

  const reasons = reasonParts.length ? `<div class="reco-row">${reasonParts.join(", ")}</div>` : "";
  const risks = riskParts.length ? `<div class="reco-row">${riskParts.join(", ")}</div>` : "";
  const fc = reco.forecast || {};
  const range = Array.isArray(fc.range_pct) ? fc.range_pct : [];
  const fcRange = range.length >= 2 ? `${Number(range[0]).toFixed(1)}% … ${Number(range[1]).toFixed(1)}%` : "-";
  const fcBiasMap = { up: "Рост", down: "Снижение", flat: "Боковик" };
  const fcBias = fcBiasMap[fc.bias] || "Боковик";
  const actionText = actionLabel(reco.action || "HOLD");
  const scoreText = `${Number(reco.reco_score ?? 0).toFixed(1)}`;
  const confidenceText = `${Math.round(Number(reco.confidence ?? 0))}%`;
  el.variantRecoBody.innerHTML = `
    <div class="stack reco-stack">
      <div class="muted">Итог</div>
      <div class="reco-row"><strong>${actionText}</strong> • Оценка: <strong>${scoreText}</strong> • Уверенность: <strong>${confidenceText}</strong></div>
      <div class="reco-row">${reco.summary || "-"}</div>
      <div class="muted">Прогноз на 24ч</div>
      <div class="reco-row"><strong>Направление:</strong> ${fcBias} • <strong>Диапазон:</strong> ${fcRange} • <strong>Уверенность:</strong> ${fc.confidence ?? reco.confidence ?? 0}%</div>
      <div class="muted">Причины</div>
      ${reasons || `<div class="empty-state">Нет причин</div>`}
      <div class="muted">Риски</div>
      ${risks || `<div class="empty-state">Нет рисков</div>`}
    </div>
  `;

  state.listings.rows = listings?.items || [];
  renderVariantListings();

  state.chart.points = resolveVariantChartPoints(series?.points || [], variant, state.chart.period);
  state.chart.start = 0;
  state.chart.end = 1;
  renderChart();
}

async function loadOverviewAndScreeners() {
  const [overview, top, shock, overheat] = await Promise.all([
    fetchJson("/api/market/overview"),
    fetchJson("/api/screeners/top-movers?entity=variant&period=24h&type=price"),
    fetchJson("/api/screeners/supply-shock?entity=variant&period=24h&type=price"),
    fetchJson("/api/screeners/overheat?entity=variant&period=24h&type=price"),
  ]);
  renderOverview(overview);
  const topItems = top.items || [];
  renderShortList(el.topMoversList, topItems, "Нет данных по росту", "price");
  renderShortList(el.supplyShockList, shock.items || [], "Нет шока предложения", "supply");
  renderShortList(el.overheatList, overheat.items || [], "Нет перегрева", "risk");
  state.overviewSignal.topItems = topItems;
  state.overviewSignal.shockItems = shock.items || [];
  state.overviewSignal.overheatItems = overheat.items || [];
  state.overviewSignal.points = buildOverviewSignalSeries(
    state.overviewSignal.topItems,
    state.overviewSignal.shockItems,
    state.overviewSignal.overheatItems,
  );
  renderOverviewSignalChart(state.overviewSignal.points);
  state.recoDay.pool = buildRecoPool(topItems, shock.items || [], overheat.items || []);
  state.recoDay.offset = 0;
  renderRecoDaySet();
  renderSignals();
  await refreshMarketAiSignal(false);
  startRecoRotation();
}

async function loadCatalog() {
  const basesResp = await fetchJson("/api/bases", {}, true);
  state.bases = basesResp.items || [];
  fillSelect(el.catalogBaseSelect, state.bases, "base_id", "name", "Выберите коллекцию");
  if (!state.catalogFilters.baseId && state.bases.length) {
    state.catalogFilters.baseId = state.bases[0].base_id;
  }
  renderBases();
  await loadCatalogFiltersAndVariants();
  state.pageLoaded.catalog = true;
}

async function loadVariantsForFilters(force = false) {
  const nowMs = Date.now();
  if (!force && state.variants.length && (nowMs - state.variantsCache.loadedAtMs) < state.variantsCache.ttlMs) {
    return;
  }
  if (force || !state.bases.length) {
    const basesResp = await fetchJson("/api/bases", {}, !force);
    state.bases = basesResp.items || [];
    if (el.catalogBaseSelect) {
      fillSelect(el.catalogBaseSelect, state.bases, "base_id", "name", "Выберите коллекцию");
      if (state.catalogFilters.baseId && !state.bases.some((b) => b.base_id === state.catalogFilters.baseId)) {
        state.catalogFilters.baseId = state.bases[0]?.base_id || "";
      }
    }
    if (!state.bases.length) {
      state.variants = [];
      state.variantsCache.loadedAtMs = nowMs;
      return;
    }
  }
  const pageSize = 400;
  const chunks = await Promise.all(
    state.bases.map(async (b) => {
      const all = [];
      let page = 1;
      let total = 0;
      do {
        const resp = await fetchJson(`/api/bases/${b.base_id}/variants?page=${page}&page_size=${pageSize}`);
        const items = resp.items || [];
        total = Number(resp.total || items.length || 0);
        all.push(...items);
        page += 1;
      } while (all.length < total && page <= 100);
      return { items: all };
    })
  );
  const merged = [];
  const seen = new Set();
  for (const resp of chunks) {
    for (const item of resp.items || []) {
      const id = item?.variant_id;
      if (!id || seen.has(id)) continue;
      seen.add(id);
      merged.push(item);
    }
  }
  state.variants = merged;
  state.variantsCache.loadedAtMs = Date.now();
  renderWatchlist();
  renderSignals();
  state.pageLoaded.watchlist = true;
  state.pageLoaded.signals = true;
}

async function loadScreenersPage() {
  const type = el.screenerType.value;
  const resp = await fetchJson(`/api/screeners/${type}?entity=variant&period=24h&type=price`);
  renderScreeners(resp.items || []);
  state.pageLoaded.screeners = true;
}

async function loadSignalsPage() {
  const filter = state.signals.filter || "all";
  const resp = await fetchJson(`/api/signals/latest?filter=${encodeURIComponent(filter)}&limit=5000`, { cache: "no-store" });
  state.signals.items = resp.items || [];
  state.signals.buyTotal = Number(resp.buy_total || 0);
  state.signals.sellTotal = Number(resp.sell_total || 0);
  renderSignals();
  state.pageLoaded.signals = true;
}

async function loadAlerts() {
  const resp = await fetchJson("/api/alerts", {}, true);
  el.alertsJson.textContent = JSON.stringify(resp.items || [], null, 2);
  state.pageLoaded.alerts = true;
}

async function openVariant(variantId) {
  state.selectedVariantId = variantId;
  localStorage.setItem(STORAGE_VARIANT_KEY, variantId);
  setPage("variant-details");
  try {
    const [variant, listings, series] = await Promise.all([
      fetchJson(`/api/variants/${variantId}`),
      fetchJson(`/api/variants/${variantId}/listings`),
      fetchJson(`/api/variants/${variantId}/timeseries?metric=floor&period=${state.chart.period}`),
    ]);
    renderVariantDetails(variant, listings, series);
  } catch (e) {
    el.variantTitle.textContent = "Ошибка загрузки карточки";
    el.variantRecoBody.innerHTML = `<div class="error-state">${e.message}</div>`;
  }
}

async function openBase(baseId) {
  state.selectedBaseId = baseId;
  localStorage.setItem(STORAGE_BASE_KEY, baseId);
  setPage("base-details");
  try {
    const base = state.bases.find((b) => b.base_id === baseId);
    const resp = await fetchJson(`/api/bases/${baseId}/variants?page=1&page_size=300`);
    renderBaseDetails(base, resp.items || []);
  } catch (e) {
    el.baseTitle.textContent = "Ошибка загрузки коллекции";
    el.baseVariantsBody.innerHTML = `<tr><td colspan="7"><div class="error-state">${e.message}</div></td></tr>`;
  }
}

function toggleWatchlist(variantId) {
  if (state.watchlist.has(variantId)) state.watchlist.delete(variantId);
  else state.watchlist.add(variantId);
  localStorage.setItem("watchlist_variants", JSON.stringify([...state.watchlist]));
  renderWatchlist();
}

function applySearch() {
  const q = (el.globalSearch.value || "").trim().toLowerCase();
  if (!q) return;
  const variant = state.variants.find((v) => v.variant_id.toLowerCase().includes(q));
  if (variant) {
    openVariant(variant.variant_id);
    return;
  }
  const base = state.bases.find((b) => b.base_id.toLowerCase().includes(q) || b.name.toLowerCase().includes(q));
  if (base) {
    openBase(base.base_id);
    return;
  }
  showToast("Ничего не найдено");
}

function bindEvents() {
  if (eventsBound) return;
  eventsBound = true;
  bindOverviewSignalTooltip();
  initAllCustomSelects();

  [...el.navBtns, ...el.mobileNavBtns].forEach((btn) => {
    btn.addEventListener("click", () => setPage(btn.dataset.page));
  });

  el.backToCatalog.addEventListener("click", () => setPage("catalog"));
  el.backToCatalogFromBase.addEventListener("click", () => setPage("catalog"));
  el.baseSearch.addEventListener("input", renderBases);
  el.catalogBaseSelect.addEventListener("change", async () => {
    state.catalogFilters.baseId = el.catalogBaseSelect.value || "";
    syncCustomSelect(el.catalogBaseSelect);
    state.catalogFilters.modelId = "";
    state.catalogFilters.backgroundIds = [];
    state.catalogFilters.patternIds = [];
    await loadCatalogFiltersAndVariants();
  });
  el.catalogModelSelect.addEventListener("change", async () => {
    state.catalogFilters.modelId = el.catalogModelSelect.value || "";
    await loadCatalogFiltersAndVariants();
  });
  el.catalogBackgroundSelect.addEventListener("change", async () => {
    state.catalogFilters.backgroundIds = selectedValues(el.catalogBackgroundSelect);
    await loadCatalogFiltersAndVariants();
  });
  el.catalogPatternSelect.addEventListener("change", async () => {
    state.catalogFilters.patternIds = selectedValues(el.catalogPatternSelect);
    await loadCatalogFiltersAndVariants();
  });
  el.screenerType.addEventListener("change", loadScreenersPage);
  if (el.signalFilterAll) el.signalFilterAll.addEventListener("click", () => setSignalFilter("all"));
  if (el.signalFilterBuy) el.signalFilterBuy.addEventListener("click", () => setSignalFilter("buy"));
  if (el.signalFilterSell) el.signalFilterSell.addEventListener("click", () => setSignalFilter("sell"));
  if (el.catalogFiltersToggleBtn) {
    el.catalogFiltersToggleBtn.addEventListener("click", () => {
      setCatalogFiltersCollapsed(!state.ui.catalogFiltersCollapsed);
    });
  }
  if (el.overviewSignalPeriod) {
    el.overviewSignalPeriod.value = state.overviewSignal.period;
    syncCustomSelect(el.overviewSignalPeriod);
    el.overviewSignalPeriod.addEventListener("change", () => {
      state.overviewSignal.period = el.overviewSignalPeriod.value || "1h";
      state.overviewSignal.points = buildOverviewSignalSeries(
        state.overviewSignal.topItems || [],
        state.overviewSignal.shockItems || [],
        state.overviewSignal.overheatItems || [],
      );
      renderOverviewSignalChart(state.overviewSignal.points);
    });
  }
  setSignalFilter(state.signals.filter);
  setCatalogFiltersCollapsed(true);
  syncCustomSelect(el.screenerType);
  syncCustomSelect(el.chartPeriod);
  syncCustomSelect(el.listingsSortField);

  el.globalSearch.addEventListener("keydown", (e) => {
    if (e.key === "Enter") applySearch();
  });

  el.showStars.value = state.showStars;
  syncCustomSelect(el.showStars);
  el.showStars.addEventListener("change", () => {
    state.showStars = el.showStars.value;
    localStorage.setItem("show_stars", state.showStars);
    renderBases();
    renderWatchlist();
    loadScreenersPage();
  });

  el.listingsSortField.addEventListener("change", () => {
    state.listings.sortField = el.listingsSortField.value;
    renderVariantListings();
  });

  el.listingsSortDir.addEventListener("click", () => {
    state.listings.sortDir = state.listings.sortDir === "asc" ? "desc" : "asc";
    el.listingsSortDir.dataset.dir = state.listings.sortDir;
    el.listingsSortDir.textContent = state.listings.sortDir === "asc" ? "По возрастанию" : "По убыванию";
    renderVariantListings();
  });

  el.chartPeriod.addEventListener("change", async () => {
    if (!state.selectedVariantId) return;
    state.chart.period = el.chartPeriod.value;
    try {
      const series = await fetchJson(`/api/variants/${state.selectedVariantId}/timeseries?metric=floor&period=${state.chart.period}`);
      state.chart.points = resolveVariantChartPoints(series?.points || [], currentVariantForChart(), state.chart.period);
      state.chart.start = 0;
      state.chart.end = 1;
      renderChart();
    } catch (e) {
      showToast(`Ошибка графика: ${e.message}`);
    }
  });

  el.chartReset.addEventListener("click", () => {
    state.chart.start = 0;
    state.chart.end = 1;
    renderChart();
  });

  el.variantChart.addEventListener("wheel", (e) => {
    e.preventDefault();
    chartZoom(e.clientX, e.deltaY);
  }, { passive: false });

  el.variantChart.addEventListener("mousedown", (e) => {
    state.chart.dragging = true;
    state.chart.dragX = e.clientX;
  });

  window.addEventListener("mouseup", () => {
    state.chart.dragging = false;
  });

  el.variantChart.addEventListener("mousemove", (e) => {
    if (state.chart.dragging) {
      chartPan(e.clientX - state.chart.dragX);
      state.chart.dragX = e.clientX;
      el.chartTooltip.classList.add("hidden");
      return;
    }
    showChartTooltip(e.clientX, e.clientY);
  });

  el.variantChart.addEventListener("mouseleave", () => {
    el.chartTooltip.classList.add("hidden");
  });

  el.refreshBtn.addEventListener("click", async () => {
    el.refreshBtn.disabled = true;
    try {
      const refresh = await fetchJson("/api/admin/refresh", { method: "POST" });
      if (refresh?.running) {
        await waitForManualRefreshDone(120000, 2000);
      }
      state.requestCache.clear();
      state.variantsCache.loadedAtMs = 0;
      await loadAll();
      await loadSignalsPage();
      if (refresh?.started === false) {
        showToast("Обновление уже выполняется");
      } else if (refresh?.mode === "full") {
        showToast("Запущен полный синк с Fragment");
      } else {
        showToast("Обновлена аналитика");
      }
    } catch (e) {
      showToast(`Ошибка обновления: ${e.message}`);
    } finally {
      el.refreshBtn.disabled = false;
    }
  });

  el.addAlertBtn.addEventListener("click", async () => {
    const sampleVariant = state.variants[0]?.variant_id || "sample_variant_id";
    const sample = {
      version: 1,
      name: "Падение floor на 10% за 24ч",
      entity: { type: "VARIANT", id: sampleVariant },
      conditions: [{ metric: "floor_change_pct_24h", op: "<=", value: -10 }],
      aggregation: { window: "24h" },
      delivery: { channels: ["WEB_PUSH"], debounce_minutes: 10 },
      message_template: {
        title: "Падение floor",
        body: "{title}: floor {floor_ton} TON (≈ {floor_stars_est}⭐), Δ24h {floor_change_pct_24h}%",
      },
    };
    try {
      await fetchJson("/api/alerts", { method: "POST", body: JSON.stringify(sample) });
      state.requestCache.delete("/api/alerts");
      await loadAlerts();
      showToast("Алерт добавлен");
    } catch (e) {
      showToast(`Ошибка алерта: ${e.message}`);
    }
  });

  document.addEventListener("click", (e) => {
    if (el.headerTonWallet && !e.target.closest("#headerTonWallet")) {
      closeTonWalletDropdown();
    }
    if (!e.target.closest(".custom-select")) {
      closeAllCustomSelects();
    }

    const variantBtn = e.target.closest(".open-variant");
    if (variantBtn) {
      openVariant(variantBtn.dataset.variant);
      return;
    }

    const baseBtn = e.target.closest(".open-base");
    if (baseBtn) {
      openBase(baseBtn.dataset.base);
      return;
    }

    const toggleBtn = e.target.closest(".toggle-watch");
    if (toggleBtn) {
      toggleWatchlist(toggleBtn.dataset.variant);
    }
  });

  el.authLogoutBtn.addEventListener("click", async () => {
    try {
      await fetchJson("/api/auth/logout", { method: "POST", cache: "no-store" });
    } catch (e) {
      // no-op: logout must continue locally even if request failed
    }
    state.auth.authenticated = false;
    state.auth.user = null;
    state.requestCache.clear();
    renderAuthUi();
    showToast("Вы вышли из аккаунта");
  });

  if (el.tonConnectBtn) {
    el.tonConnectBtn.addEventListener("click", connectTonWallet);
  }
  if (el.headerTonConnectBtn) {
    el.headerTonConnectBtn.addEventListener("click", async () => {
      if (state.ton.connected) {
        toggleTonWalletDropdown();
        return;
      }
      await connectTonWallet();
    });
  }
  if (el.headerTonMenuBtn) {
    el.headerTonMenuBtn.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      toggleTonWalletDropdown();
    });
  }
  if (el.headerTonDisconnectBtn) {
    el.headerTonDisconnectBtn.addEventListener("click", async () => {
      await disconnectTonWallet();
    });
  }
  if (el.tonDisconnectBtn) {
    el.tonDisconnectBtn.addEventListener("click", disconnectTonWallet);
  }
}

async function loadAll() {
  if (state.auth.required && !state.auth.authenticated) {
    setAuthLocked(true, "Для доступа к аналитике выполните вход через Telegram.");
    return;
  }
  document.body.classList.add("loading");
  try {
    state.starsRate = await fetchJson("/api/rates/stars", {}, true);
    await loadOverviewAndScreeners();
    state.pageLoaded.overview = true;
  } catch (e) {
    el.statusLine.textContent = `Ошибка загрузки: ${e.message}`;
  } finally {
    document.body.classList.remove("loading");
  }

  const activePage = window.location.hash.replace("#", "") || localStorage.getItem(STORAGE_PAGE_KEY) || "overview";
  const allowed = new Set(["overview", "catalog", "screeners", "signals", "watchlist", "alerts", "settings", "base-details", "variant-details"]);
  const pageToOpen = allowed.has(activePage) ? activePage : "overview";

  if (pageToOpen === "variant-details") {
    const variantId = localStorage.getItem(STORAGE_VARIANT_KEY) || state.selectedVariantId;
    if (variantId) {
      await ensurePageData("catalog");
      await openVariant(variantId);
      return;
    }
  }
  if (pageToOpen === "base-details") {
    const baseId = localStorage.getItem(STORAGE_BASE_KEY) || state.selectedBaseId;
    if (baseId) {
      await ensurePageData("catalog");
      await openBase(baseId);
      return;
    }
  }
  setPage(pageToOpen);
}

async function ensurePageData(pageId) {
  if (pageId === "overview") {
    if (!state.pageLoaded.overview) {
      await loadOverviewAndScreeners();
      state.pageLoaded.overview = true;
    }
    return;
  }
  if (pageId === "catalog" || pageId === "base-details" || pageId === "variant-details" || pageId === "watchlist") {
    if (!state.pageLoaded.catalog) {
      await loadCatalog();
    }
    await loadVariantsForFilters(false);
    return;
  }
  if (pageId === "screeners") {
    if (!state.pageLoaded.screeners) {
      await loadScreenersPage();
    }
    return;
  }
  if (pageId === "signals") {
    await loadSignalsPage();
    return;
  }
  if (pageId === "alerts") {
    if (!state.pageLoaded.alerts) {
      await loadAlerts();
    }
  }
}

async function autoSyncTick() {
  if (state.autoSync.inProgress) return;
  state.autoSync.inProgress = true;
  try {
    state.requestCache.clear();
    await loadOverviewAndScreeners();

    const activePage = document.querySelector(".page.active")?.id || "overview";
    if (activePage === "catalog" || activePage === "base-details" || activePage === "watchlist") {
      await loadCatalog();
      await loadVariantsForFilters(false);
      if (activePage === "base-details" && state.selectedBaseId) {
        await openBase(state.selectedBaseId);
      }
    } else if (activePage === "screeners") {
      await loadScreenersPage();
    } else if (activePage === "signals") {
      await loadSignalsPage();
    } else if (activePage === "variant-details" && state.selectedVariantId) {
      await openVariant(state.selectedVariantId);
    }
  } catch (e) {
    // Silent fail on background sync; UI keeps the last successful state.
  } finally {
    state.autoSync.inProgress = false;
  }
}

function startAutoSync() {
  if (state.autoSync.timer) return;
  state.autoSync.timer = setInterval(() => {
    if (document.hidden) return;
    autoSyncTick();
  }, state.autoSync.intervalMs);
}

async function bootstrap() {
  if (bootstrapped) return;
  bootstrapped = true;
  bindEvents();
  state.auth.webappDetected = detectTelegramMiniAppContext();
  const tonInitPromise = initTonAuth();
  const webAppPreAuth = await tryTelegramWebAppLogin();
  const ready = await initAuth();
  if (!webAppPreAuth) {
    scheduleWebAppAuthRetry();
  }
  const url = new URL(window.location.href);
  const authState = url.searchParams.get("auth");
  if (authState === "telegram_failed") {
    const reason = url.searchParams.get("reason") || "unknown";
    showToast(`Ошибка входа Telegram: ${reason}`);
  }
  if (authState) {
    url.searchParams.delete("auth");
    url.searchParams.delete("reason");
    history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
    await refreshAuthMe();
    renderAuthUi();
  }
  if (ready) {
    await loadAll();
    startAutoSync();
  }
  await tonInitPromise;
}

bootstrap();
