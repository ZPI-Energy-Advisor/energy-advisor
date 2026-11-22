import { useCallback, useEffect, useRef, useState } from "react";
import apiClient from "../api/client";
import { getApiErrorMessage } from "../utils/energyFiles";

/**
 * Ostatni przebieg planu z GET /home/plan-runs/latest (null, gdy żadnego nie było).
 *
 * Nie odpytuje backendu sam: ekran „Mój dom” i tak odświeża stan domu, więc przebieg pobieramy, gdy zmieni
 * się czas albo przebieg symulacji (`simTime`, `simulationId`), a po poleceniu przez `refresh`.
 * `replace` podmienia przebieg odpowiedzią z polecenia (np. „Zakończ”) bez kolejnego żądania.
 */
export function usePlanRun(simTime, simulationId) {
  const [run, setRun] = useState(undefined);
  const [error, setError] = useState(null);
  const [reloadKey, setReloadKey] = useState(0);
  const version = useRef(0);
  const refresh = useCallback(() => setReloadKey((key) => key + 1), []);
  const replace = useCallback((next) => {
    version.current += 1;
    setRun(next);
  }, []);

  useEffect(() => {
    let cancelled = false;
    const started = version.current;
    apiClient
      .get("/home/plan-runs/latest")
      .then(({ data }) => {
        if (cancelled || version.current !== started) return;
        setRun(data ?? null);
        setError(null);
      })
      .catch((err) => {
        if (!cancelled) setError(getApiErrorMessage(err, "Nie udało się pobrać przebiegu planu."));
      });
    return () => {
      cancelled = true;
    };
  }, [simTime, simulationId, reloadKey]);

  return { run, error, refresh, replace };
}
