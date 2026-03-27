const LS_AUTO_REFRESH_MIN = 'gmz:settings:auto_refresh_min'
const AUTO_REFRESH_MIN_MINUTES = 1
const AUTO_REFRESH_MAX_MINUTES = 10
const AUTO_REFRESH_DEFAULT_MINUTES = 2

function clampAutoRefreshMinutes(value: number): number {
  if (!Number.isFinite(value)) return AUTO_REFRESH_DEFAULT_MINUTES
  const rounded = Math.round(value)
  return Math.max(AUTO_REFRESH_MIN_MINUTES, Math.min(AUTO_REFRESH_MAX_MINUTES, rounded))
}

export function uiAutoRefreshBounds() {
  return {
    min: AUTO_REFRESH_MIN_MINUTES,
    max: AUTO_REFRESH_MAX_MINUTES,
    defaultValue: AUTO_REFRESH_DEFAULT_MINUTES,
  }
}

export function readUiAutoRefreshMinutes(): number {
  try {
    const raw = localStorage.getItem(LS_AUTO_REFRESH_MIN)
    if (!raw) return AUTO_REFRESH_DEFAULT_MINUTES
    return clampAutoRefreshMinutes(Number(raw))
  } catch {
    return AUTO_REFRESH_DEFAULT_MINUTES
  }
}

export function writeUiAutoRefreshMinutes(value: number): number {
  const safe = clampAutoRefreshMinutes(value)
  try {
    localStorage.setItem(LS_AUTO_REFRESH_MIN, String(safe))
  } catch {
    // ignore
  }
  return safe
}

export function uiAutoRefreshMs(minutes?: number): number {
  const safe = minutes === undefined ? readUiAutoRefreshMinutes() : clampAutoRefreshMinutes(minutes)
  return safe * 60_000
}

