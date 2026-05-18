// ui/modules/api.js

import { invalidateInitialCache } from './cache.js';

export class ApiError extends Error {
  constructor(message, { status = 0, statusText = '', data = null, body = '' } = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.statusText = statusText;
    this.data = data;
    this.body = body;
  }
}

const parseResponseBody = async (res) => {
  const text = await res.text();
  if (!text) return null;

  try {
    return JSON.parse(text);
  } catch (err) {
    if (res.ok) {
      throw new ApiError('Invalid JSON response', {
        status: res.status,
        statusText: res.statusText,
        body: text,
      });
    }
    return text;
  }
};

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
  const data = await parseResponseBody(res);

  if (!res.ok) {
    const serverMessage = data && typeof data === 'object'
      ? (data.error || data.message)
      : data;
    const message = serverMessage || `${res.status} ${res.statusText || 'HTTP error'}`;
    throw new ApiError(String(message), {
      status: res.status,
      statusText: res.statusText,
      data: data && typeof data === 'object' ? data : null,
      body: typeof data === 'string' ? data : '',
    });
  }

  return data;
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
