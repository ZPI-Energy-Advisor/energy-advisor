import { useCallback, useEffect, useMemo, useState } from "react";
import apiClient from "../api/client";
import { CurrentUserContext } from "./currentUserContext";
import { getApiErrorMessage } from "../utils/energyFiles";

export function CurrentUserProvider({ children }) {
  const [me, setMe] = useState(null);
  const [isReady, setIsReady] = useState(false);
  const [loadError, setLoadError] = useState(null);

  const refresh = useCallback(async () => {
    try {
      const { data } = await apiClient.get("/users/me");
      setMe(data);
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
    }),
    [me, isReady, loadError, refresh],
  );

  return <CurrentUserContext.Provider value={value}>{children}</CurrentUserContext.Provider>;
}
