// Per-browser UI preferences (favorites + recently-used tools), kept in localStorage.
// A lightweight "selfx-prefs" window event lets open views refresh when these change.

const FAV_KEY = "selfx_favorites";
const RECENT_KEY = "selfx_recent_tools";
const RECENT_MAX = 8;

export const PREFS_EVENT = "selfx-prefs";

function read(key: string): string[] {
  try {
    const v = JSON.parse(localStorage.getItem(key) || "[]");
    return Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [];
  } catch {
    return [];
  }
}

function write(key: string, list: string[]): void {
  try {
    localStorage.setItem(key, JSON.stringify(list));
  } catch {
    // storage disabled or over quota — favorites/recents are best-effort
  }
  if (typeof window !== "undefined") window.dispatchEvent(new Event(PREFS_EVENT));
}

export function getFavorites(): string[] {
  return read(FAV_KEY);
}

export function isFavorite(slug: string): boolean {
  return read(FAV_KEY).includes(slug);
}

/** Toggle a tool's favorite state; returns the new state (true = now favorited). */
export function toggleFavorite(slug: string): boolean {
  const cur = read(FAV_KEY);
  const has = cur.includes(slug);
  write(FAV_KEY, has ? cur.filter((s) => s !== slug) : [slug, ...cur]);
  return !has;
}

export function getRecentTools(): string[] {
  return read(RECENT_KEY);
}

/** Record a tool as most-recently used (deduped, capped). */
export function addRecentTool(slug: string): void {
  const cur = read(RECENT_KEY).filter((s) => s !== slug);
  write(RECENT_KEY, [slug, ...cur].slice(0, RECENT_MAX));
}
