import { useCallback, useEffect, useMemo, useState } from "react";
import apiClient from "../api/client";
import { CurrentUserContext } from "./currentUserContext";
import { getApiErrorMessage } from "../utils/energyFiles";

export function CurrentUserProvider({ children }) {
  const [me, setMe] = useState(null);
  const [isReady, setIsReady] = useState(false);
  const [loadError, setLoadError] = useState(null);
  // Rośnie po każdym pobraniu konta (np. po zapisaniu profilu), żeby ekrany z kosztami pobrały je od nowa.
  const [version, setVersion] = useState(0);

  const refresh = useCallback(async () => {
    try {
      const { data } = await apiClient.get("/users/me");
      setMe(data);
      setVersion((current) => current + 1);
      setLoadError(null);
    } catch (error) {
      setLoadError(getApiErrorMessage(error, "Nie udało się pobrać danych konta."));
    } finally {
      setIsReady(true);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    Promise.resolve().then(() => {
      if (!cancelled) refresh();
    });
    return () => {
      cancelled = true;
    };
  }, [refresh]);

  const value = useMemo(
    () => ({
      me,
      currentTariff: me?.current_tariff ?? null,
      profileTariff: me?.profile ?? null,
      isReady,
      loadError,
      refresh,
      version,
    }),
    [me, isReady, loadError, refresh, version],
  );

  return <CurrentUserContext.Provider value={value}>{children}</CurrentUserContext.Provider>;
}
