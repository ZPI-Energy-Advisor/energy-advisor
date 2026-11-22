import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import apiClient from "../api/client";
import { getApiErrorMessage } from "../utils/energyFiles";
import { createResponseCache } from "../utils/responseCache";

export const comparisonCache = createResponseCache(10);

const comparisonKey = (scope, source) =>
  source ? `${scope}|${source.fileId}|${source.range ? `${source.range.from}|${source.range.to}` : "full"}` : null;

// Porównanie taryf dla pliku i zakresu. Poprzedni wynik zostaje na ekranie do czasu nowego,
// a spóźniona odpowiedź na starsze zapytanie go nie podmienia.
export function useTariffComparison(source, scope) {
  const key = comparisonKey(scope, source);
  const readCached = useCallback(() => (key ? comparisonCache.get(key) : undefined), [key]);
  const cached = useSyncExternalStore(comparisonCache.subscribe, readCached);
  const [shown, setShown] = useState(null);
  const [failure, setFailure] = useState(null);
  const latestRef = useRef(0);

  useEffect(() => {
    if (!key) return undefined;
    const requestId = ++latestRef.current;
    const hit = comparisonCache.get(key);
    if (hit) {
      comparisonCache.touch(key);
      Promise.resolve().then(() => {
        if (requestId === latestRef.current) setShown(hit);
      });
      return undefined;
    }
    const { fileId, range } = source;
    apiClient
      .get(`/energy-files/${fileId}/tariff-comparison`, { params: range ? { from: range.from, to: range.to } : {} })
      .then(({ data }) => {
        comparisonCache.set(key, data);
        if (requestId !== latestRef.current) return;
        setShown(data);
        setFailure(null);
      })
      .catch((error) => {
        if (requestId !== latestRef.current) return;
        setFailure({ key, message: getApiErrorMessage(error, "Nie udało się porównać taryf.") });
      });
    return undefined;
  }, [key, source]);

  const error = failure?.key === key ? failure.message : null;
  return {
    comparison: cached ?? (error ? null : shown),
    isLoading: Boolean(key) && !cached && !error,
    error,
  };
}
