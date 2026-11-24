import { useCallback, useContext, useEffect, useState, useSyncExternalStore } from "react";
import apiClient from "../api/client";
import { CurrentUserContext } from "../context/currentUserContext";
import { EnergyFileContext } from "../context/energyFileContext";
import { getApiErrorMessage } from "../utils/energyFiles";

const noSubscription = () => () => {};

/**
 * Zużycie i koszt urządzeń z GET /energy-files/{źródło}/devices/usage (ZP-81).
 * `request` to { sourceId, params } albo null, gdy nie ma czego pobierać. Podczas ładowania
 * zwracamy poprzednią odpowiedź, żeby wykres nie znikał przy zmianie poziomu albo zakresu.
 * Ostatnie odpowiedzi są w pamięci EnergyFileProvider (czyszczonej po zmianie plików), więc powrót
 * do wcześniejszego poziomu, zakresu albo rozdzielczości jest natychmiastowy. Spóźniona odpowiedź
 * na wcześniejsze zapytanie trafia tylko do pamięci, nie na ekran.
 */
export function useDeviceUsage(request) {
  // Koszty zależą od profilu, więc po jego zmianie (nowa wersja konta) pobieramy dane ponownie.
  const userVersion = useContext(CurrentUserContext)?.version ?? 0;
  const files = useContext(EnergyFileContext);
  const cache = files?.deviceUsageCache ?? null;
  const scope = files?.cacheScope ?? "";
  const key = request ? JSON.stringify({ ...request, userVersion, scope }) : null;
  const readCached = useCallback(() => (key && cache ? cache.get(key) : undefined), [key, cache]);
  const cached = useSyncExternalStore(cache?.subscribe ?? noSubscription, readCached);
  const [state, setState] = useState({ key: null, data: null, error: null });

  useEffect(() => {
    if (!key || (cache && cache.get(key))) {
      if (key && cache) cache.touch(key);
      return undefined;
    }
    let cancelled = false;
    const { sourceId, params } = JSON.parse(key);
    apiClient.get(`/energy-files/${sourceId}/devices/usage`, { params }).then(
      ({ data }) => {
        cache?.set(key, data);
        if (!cancelled) setState({ key, data, error: null });
      },
      (error) => {
        if (!cancelled) {
          setState({
            key,
            data: null,
            error: getApiErrorMessage(error, "Nie udało się pobrać zużycia urządzeń."),
          });
        }
      },
    );
    return () => {
      cancelled = true;
    };
  }, [key, cache]);

  const isCurrent = key !== null && (cached !== undefined || state.key === key);
  return {
    data: cached ?? state.data,
    error: isCurrent && cached === undefined ? state.error : null,
    isLoading: key !== null && !isCurrent,
  };
}
