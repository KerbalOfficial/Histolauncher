// ui/modules/cache.js

export const CACHE_INIT_KEY = 'histolauncher_init_cache_v2';

let initialCacheDirty = false;

export const isInitialCacheDirty = () => initialCacheDirty;

export const trimInitialDataForCache = (data) => {
  if (!data || typeof data !== 'object') return data;
  const out = { ...data };
  delete out.versions;
  return out;
};

export const loadCachedInitialData = () => {
  try {
    const raw = localStorage.getItem(CACHE_INIT_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return parsed;
  } catch (e) {
    return null;
  }
};

export const saveCachedInitialData = (data) => {
  try {
    const trimmed = trimInitialDataForCache(data);
    localStorage.setItem(CACHE_INIT_KEY, JSON.stringify(trimmed));
    initialCacheDirty = false;
  } catch (e) {
    // Ignore
  }
};

export const invalidateInitialCache = () => {
  initialCacheDirty = true;
  try {
    localStorage.removeItem(CACHE_INIT_KEY);
  } catch (e) {
    // Ignore
  }
};
