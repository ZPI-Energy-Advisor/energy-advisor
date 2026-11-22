// Ostatnie odpowiedzi API w kolejności użycia; najdawniej używana wypada po przekroczeniu limitu.
// `subscribe` pozwala czytać pamięć w renderze przez useSyncExternalStore.
export const createResponseCache = (limit = 10) => {
  const entries = new Map();
  const listeners = new Set();
  const notify = () => listeners.forEach((listener) => listener());
  return {
    get(key) {
      return entries.get(key);
    },
    touch(key) {
      if (!entries.has(key)) return;
      const value = entries.get(key);
      entries.delete(key);
      entries.set(key, value);
    },
    set(key, value) {
      entries.delete(key);
      entries.set(key, value);
      while (entries.size > limit) entries.delete(entries.keys().next().value);
      notify();
    },
    clear() {
      entries.clear();
      notify();
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    get size() {
      return entries.size;
    },
  };
};
