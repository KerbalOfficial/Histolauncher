// ui/modules/api.js

import { invalidateInitialCache } from './cache.js';

export const api = async (path, method = 'GET', body = null, requestOptions = {}) => {
  const opts = { method, headers: {} };
  if (body) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  if (requestOptions && requestOptions.signal) {
    opts.signal = requestOptions.signal;
  }

  const normalizedMethod = String(method || 'GET').toUpperCase();
  if (normalizedMethod !== 'GET' && String(path || '').startsWith('/api/')) {
    invalidateInitialCache();
  }

  const res = await fetch(path, opts);
  return res.json();
};

export const createOperationId = (prefix = 'op') =>
  `${prefix}_${Date.now()}_${Math.random().toString(36).slice(2, 9)}`;

export const requestOperationCancel = async (operationId) => {
  if (!operationId) return;
  try {
    await api('/api/operations/cancel', 'POST', { operation_id: operationId });
  } catch (err) {
    console.warn('Failed to request operation cancel:', err);
  }
};
