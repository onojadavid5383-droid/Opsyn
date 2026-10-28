// ============================================================
// OPSYN API CLIENT
// Axios instance with JWT injection, refresh rotation, error normalisation
// ============================================================

import axios, { AxiosError, type AxiosInstance, type InternalAxiosRequestConfig } from 'axios';
import type { APIError } from '@shared';

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api/v1';

// ── Singleton instance ────────────────────────────────────────
export const apiClient: AxiosInstance = axios.create({
  baseURL: BASE_URL,
  timeout: 30_000,
  headers: { 'Content-Type': 'application/json' },
});

// ── Token storage helpers ─────────────────────────────────────
const TOKEN_KEY = 'opsyn_access_token';

export const tokenStore = {
  get:   ()           => localStorage.getItem(TOKEN_KEY),
  set:   (t: string)  => localStorage.setItem(TOKEN_KEY, t),
  clear: ()           => localStorage.removeItem(TOKEN_KEY),
};

// ── Request interceptor: inject JWT ──────────────────────────
apiClient.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = tokenStore.get();
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// ── Refresh queue — typed to handle both success and failure ──
interface QueueEntry {
  resolve: (token: string) => void;
  reject:  (err: unknown)  => void;
}

let isRefreshing   = false;
let refreshQueue:  QueueEntry[] = [];

const drainQueue = (error: unknown, token: string | null = null) => {
  refreshQueue.forEach(entry =>
    error ? entry.reject(error) : entry.resolve(token!)
  );
  refreshQueue = [];
};

// ── Response interceptor: 401 → refresh → retry ──────────────
apiClient.interceptors.response.use(
  res => res,
  async (error: AxiosError<APIError>) => {
    const original = error.config as (InternalAxiosRequestConfig & { _retry?: boolean }) | undefined;

    // Guard: no config, not a 401, already retried, or auth endpoint itself
    if (
      !original ||
      error.response?.status !== 401 ||
      original._retry ||
      original.url?.includes('/auth/')
    ) {
      return Promise.reject(normaliseError(error));
    }

    // Another request is already refreshing — queue this one
    if (isRefreshing) {
      return new Promise<unknown>((resolve, reject) => {
        refreshQueue.push({
          resolve: (token) => {
            original.headers.Authorization = `Bearer ${token}`;
            resolve(apiClient(original));
          },
          reject,
        });
      });
    }

    original._retry = true;
    isRefreshing    = true;

    try {
      const { data } = await axios.post(`${BASE_URL}/auth/refresh`, {}, {
        withCredentials: true, // refresh token lives in httpOnly cookie
      });
      const newToken: string = data.data?.access_token ?? data.access_token;
      tokenStore.set(newToken);
      drainQueue(null, newToken);
      original.headers.Authorization = `Bearer ${newToken}`;
      return apiClient(original);
    } catch (refreshError) {
      drainQueue(refreshError);
      const refreshStatus = axios.isAxiosError(refreshError)
        ? refreshError.response?.status
        : undefined;

      // Only discard the local session when the server has definitively
      // rejected the refresh credential. Network errors and server failures
      // are temporary; logging the user out on those loses their work and
      // guarantees the next request cannot recover.
      if (refreshStatus === 401 || refreshStatus === 403) {
        tokenStore.clear();
        localStorage.removeItem('opsyn-auth');
        window.location.href = '/login';
      }
      return Promise.reject(normaliseError(error));
    } finally {
      isRefreshing = false;
    }
  }
);

// ── Error normalisation ───────────────────────────────────────
/**
 * What a rejected request hands an onError / .catch() callback.
 *
 * Requests rejected through this module pass normaliseError() below,
 * which attaches `detail` and `status`. A few call sites read the raw
 * axios shape instead, so `response` is included. Every field is
 * optional: this documents what may be present, it promises nothing.
 */
export interface ApiError extends Error {
  detail?:   string;
  status?:   number;
  response?: {
    status?: number;
    // The unvalidated wire payload. `detail` is a string from the
    // HTTPException handler and an array of field errors from the
    // validation handler, so this stays deliberately open.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    data?: any;
  };
}

function normaliseError(error: AxiosError<APIError>): Error & { detail: string; status: number } {
  const status = error.response?.status ?? 0;
  const raw    = error.response?.data;
  let detail   = 'An unexpected error occurred';

  if (typeof raw?.detail === 'string') {
    detail = raw.detail;
  } else if (Array.isArray(raw?.detail)) {
    detail = raw.detail.map(e => e.message ?? e).join('; ');
  } else if (error.message) {
    detail = error.message;
  }

  const err    = new Error(detail) as Error & { detail: string; status: number };
  err.detail   = detail;
  err.status   = status;
  return err;
}

export default apiClient;
