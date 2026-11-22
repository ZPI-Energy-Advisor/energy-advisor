import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import apiClient from "../api/client";
import { getApiErrorMessage } from "../utils/energyFiles";

const comparisonKey = (scope, source) =>
  source ? `${scope}|${source.fileId}|${source.range ? `${source.range.from}|${source.range.to}` : "full"}` : null;

const noSubscription = () => () => {};

// Porównanie taryf dla pliku i zakresu z pamięcią `cache` (z EnergyFileProvider). Poprzedni wynik zostaje
// na ekranie do czasu nowego, a spóźniona odpowiedź na starsze zapytanie go nie podmienia.
export function useTariffComparison(source, scope, cache) {
  const key = comparisonKey(scope, source);
  const readCached = useCallback(() => (key && cache ? cache.get(key) : undefined), [key, cache]);
  const cached = useSyncExternalStore(cache?.subscribe ?? noSubscription, readCached);
  const [shown, setShown] = useState(null);
  const [failure, setFailure] = useState(null);
  const [attempt, setAttempt] = useState(0);
  const latestRef = useRef(0);

  useEffect(() => {
    if (!key || !cache) return undefined;
    const requestId = ++latestRef.current;
    const hit = cache.get(key);
    if (hit) {
      cache.touch(key);
      Promise.resolve().then(() => {
        if (requestId === latestRef.current) setShown(hit);
      });
      return undefined;
    }
    const { fileId, range } = source;
    apiClient
      .get(`/energy-files/${fileId}/tariff-comparison`, { params: range ? { from: range.from, to: range.to } : {} })
      .then(({ data }) => {
        cache.set(key, data);
        if (requestId !== latestRef.current) return;
        setShown(data);
        setFailure(null);
      })
      .catch((error) => {
        if (requestId !== latestRef.current) return;
        setFailure({ key, message: getApiErrorMessage(error, "Nie udało się porównać taryf.") });
      });
    return undefined;
  }, [key, source, cache, attempt]);

  const retry = useCallback(() => {
    setFailure(null);
    setAttempt((current) => current + 1);
  }, []);

  const error = failure?.key === key ? failure.message : null;
  return {
    comparison: cached ?? (error ? null : shown),
    isLoading: Boolean(key) && !cached && !error,
    error,
    retry,
  };
}
