/// <reference types="vitest/globals" />
// ============================================================
// OPSYN VITEST SETUP — src/test/setup.ts
// Global test configuration for React Testing Library
// ============================================================

import '@testing-library/jest-dom';

// ── Mock window.matchMedia (jsdom doesn't implement it) ───────
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  }),
});

// ── Mock IntersectionObserver ─────────────────────────────────
window.IntersectionObserver = class IntersectionObserver {
  observe()    { return null; }
  unobserve()  { return null; }
  disconnect() { return null; }
} as unknown as typeof IntersectionObserver;

// ── Mock ResizeObserver ───────────────────────────────────────
window.ResizeObserver = class ResizeObserver {
  observe()    { return null; }
  unobserve()  { return null; }
  disconnect() { return null; }
};

// ── Silence console.error for React 18 act() warnings ────────
const originalError = console.error;
beforeAll(() => {
  console.error = (...args: unknown[]) => {
    if (
      typeof args[0] === 'string' &&
      (args[0].includes('act(') || args[0].includes('ReactDOM.render'))
    ) return;
    originalError.call(console, ...args);
  };
});
afterAll(() => {
  console.error = originalError;
});
