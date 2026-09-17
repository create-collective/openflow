// jest-dom matchers (toBeVisible, toHaveClass, ...) for every unit test, and Testing Library's
// cleanup after each one: without Vitest globals it would not hook itself in, and a component
// that renders into document.body (a Modal) would then leak into the next test.
import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(cleanup);

// Node 22+ ships an experimental `localStorage` global that is an object with no methods unless
// a storage file is configured, and it shadows jsdom's when Vitest populates the globals. The
// app keeps its preferences in storage, so the tests get a real (in-memory) Storage on both the
// global and the window, cleared between tests.
class MemoryStorage {
  #m = new Map();
  get length() { return this.#m.size; }
  key(i) { return [...this.#m.keys()][i] ?? null; }
  getItem(k) { return this.#m.has(String(k)) ? this.#m.get(String(k)) : null; }
  setItem(k, v) { this.#m.set(String(k), String(v)); }
  removeItem(k) { this.#m.delete(String(k)); }
  clear() { this.#m.clear(); }
}
for (const name of ["localStorage", "sessionStorage"]) {
  if (typeof globalThis[name]?.getItem !== "function") {
    const store = new MemoryStorage();
    Object.defineProperty(globalThis, name, { value: store, configurable: true, writable: true });
    if (typeof window !== "undefined" && window !== globalThis) {
      Object.defineProperty(window, name, { value: store, configurable: true, writable: true });
    }
  }
}
afterEach(() => { localStorage.clear(); sessionStorage.clear(); });
