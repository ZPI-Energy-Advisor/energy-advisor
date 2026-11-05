import { useEffect, useState } from "react";
import apiClient from "../api/client";
import { getApiErrorMessage } from "../utils/energyFiles";

/**
 * Zużycie i koszt urządzeń z GET /energy-files/{źródło}/devices/usage (ZP-81).
 * `request` to { sourceId, params } albo null, gdy nie ma czego pobierać. Podczas ładowania
 * zwracamy poprzednią odpowiedź, żeby wykres nie znikał przy zmianie poziomu albo zakresu.
 */
export function useDeviceUsage(request) {
  const key = request ? JSON.stringify(request) : null;
  const [state, setState] = useState({ key: null, data: null, error: null });

  useEffect(() => {
    if (!key) return undefined;
    let cancelled = false;
    const { sourceId, params } = JSON.parse(key);
    apiClient.get(`/energy-files/${sourceId}/devices/usage`, { params }).then(
      ({ data }) => {
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
  }, [key]);

  const isCurrent = key !== null && state.key === key;
  return {
    data: state.data,
    error: isCurrent ? state.error : null,
    isLoading: key !== null && !isCurrent,
  };
}
