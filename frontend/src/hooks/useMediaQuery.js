import { useCallback, useSyncExternalStore } from "react";

// Szerokość telefonu: poniżej `md` (768 px) ekrany pokazują układ dla wąskiego ekranu, np. pokoje Mojego domu
// jako kafelki zamiast przekroju. Bez `matchMedia` (testy w jsdom) zwraca false, czyli układ dla komputera.
export const PHONE_QUERY = "(max-width: 767px)";

export function useMediaQuery(query) {
  const subscribe = useCallback(
    (onChange) => {
      if (typeof window === "undefined" || !window.matchMedia) return () => {};
      const list = window.matchMedia(query);
      list.addEventListener("change", onChange);
      return () => list.removeEventListener("change", onChange);
    },
    [query],
  );
  const snapshot = () => (typeof window !== "undefined" && window.matchMedia ? window.matchMedia(query).matches : false);
  return useSyncExternalStore(subscribe, snapshot, () => false);
}

export const useIsPhone = () => useMediaQuery(PHONE_QUERY);
