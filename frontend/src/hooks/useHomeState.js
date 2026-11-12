import { useCallback, useEffect, useState } from "react";
import apiClient from "../api/client";
import { getApiErrorMessage } from "../utils/energyFiles";

// Działający zegar zmienia stan co kwadrans symulacji (przy tempie 288 co ~3 s), więc pytamy co 2 s.
// Zatrzymany zegar zmieniają tylko polecenia z tego ekranu, a po nich stan jest pobierany od razu.
export const RUNNING_POLL_MS = 2000;
export const PAUSED_POLL_MS = 10000;

/**
 * Stan domu z GET /home/state odświeżany cyklicznie, dopóki komponent jest zamontowany.
 *
 * Używa go komponent widoczny tylko przy podłączonym domu, więc odłączenie domu go odmontowuje
 * i po ponownym podłączeniu stan zaczyna się od zera, bez danych poprzedniego przebiegu.
 *
 * Kolejne żądanie wychodzi dopiero po odpowiedzi poprzedniego, więc wolny backend nie dostaje
 * zalewu żądań. Ukryta karta nie odpytuje backendu; po powrocie stan jest pobierany od razu.
 * Błąd odświeżenia nie czyści ostatniego stanu, tylko zostaje pokazany obok niego.
 */
export function useHomeState() {
  const [state, setState] = useState(null);
  const [error, setError] = useState(null);
  const [reloadKey, setReloadKey] = useState(0);
  const refresh = useCallback(() => setReloadKey((key) => key + 1), []);

  useEffect(() => {
    let cancelled = false;
    let inFlight = false;
    let timer = null;

    const load = async () => {
      clearTimeout(timer);
      if (inFlight || document.hidden) return;
      inFlight = true;
      let delay = PAUSED_POLL_MS;
      try {
        const { data } = await apiClient.get("/home/state");
        if (cancelled) return;
        setState(data);
        setError(null);
        if (data.clock?.running) delay = RUNNING_POLL_MS;
      } catch (err) {
        if (cancelled) return;
        setError(getApiErrorMessage(err, "Nie udało się pobrać stanu domu."));
      } finally {
        inFlight = false;
      }
      if (!cancelled) timer = setTimeout(load, delay);
    };

    const onVisibilityChange = () => {
      if (!document.hidden) load();
    };

    document.addEventListener("visibilitychange", onVisibilityChange);
    load();
    return () => {
      cancelled = true;
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [reloadKey]);

  return { state, error, isLoading: !state && !error, refresh };
}
