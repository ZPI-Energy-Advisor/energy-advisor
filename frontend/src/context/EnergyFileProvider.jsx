import { useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import apiClient, { selectedFileStorageKey } from "../api/client";
import { CurrentUserContext } from "./currentUserContext";
import { EnergyFileContext } from "./energyFileContext";
import { aggregateIdForSourceType, getApiErrorMessage, normalizeRange } from "../utils/energyFiles";
import { createResponseCache } from "../utils/responseCache";

const PAGE_SIZE = 20;
const DATA_CACHE_LIMIT = 10;
const COMPARISON_CACHE_LIMIT = 10;

const getStoredUserId = () => {
  try {
    return JSON.parse(localStorage.getItem("user"))?.id ?? null;
  } catch {
    return null;
  }
};

const storageKey = selectedFileStorageKey;

const readStoredFileId = (userId) => {
  try {
    return localStorage.getItem(storageKey(userId));
  } catch {
    return null;
  }
};

const writeStoredFileId = (userId, fileId) => {
  try {
    localStorage.setItem(storageKey(userId), fileId);
  } catch {
    // brak dostępu do localStorage - wybór zostanie tylko w stanie aplikacji
  }
};

const rangeKey = (range) => (range ? `${range.from}|${range.to}` : "full");

const rangeFromKey = (key) => {
  if (!key || key === "full") return null;
  const [from, to] = key.split("|");
  return { from, to };
};

const sourceKey = (source) => `${source.fileId}|${rangeKey(source.range)}`;

const sourceFromKey = (key) => {
  const [fileId, ...range] = key.split("|");
  return { fileId, range: rangeFromKey(range.join("|")) };
};

const dataKey = (fileId, range, tariffs) => `${fileId}|${rangeKey(range)}|${tariffs}`;

export function EnergyFileProvider({ children }) {
  const [userId] = useState(getStoredUserId);

  // files to pozycje aktualnie wyświetlanej strony tabeli.
  const [files, setFiles] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(0);
  const [isLoadingFiles, setIsLoadingFiles] = useState(false);
  const [filesError, setFilesError] = useState(null);
  // Podsumowanie źródła "Wszystkie pliki" (zakres i liczba plików) albo null, gdy brak gotowych plików.
  const [aggregate, setAggregate] = useState(null);
  const [devicesAggregate, setDevicesAggregate] = useState(null);
  const [deletingFileId, setDeletingFileId] = useState(null);
  const [deleteError, setDeleteError] = useState(null);

  // fileData zawiera { file, simulation_id, results } ostatnio poprawnie pobranego pliku.
  const [fileData, setFileData] = useState(null);
  // Plik i zakres zapytania w toku (zakres null = cały okres pliku).
  const [pendingSource, setPendingSource] = useState(null);
  const [dataError, setDataError] = useState(null);
  const [rangeError, setRangeError] = useState(null);
  const [isReady, setIsReady] = useState(false);
  // Rośnie po wgraniu, usunięciu i ponownym wczytaniu plików: dane zbiorcze i odpowiedzi w pamięci są wtedy nieaktualne.
  const [filesVersion, setFilesVersion] = useState(0);
  // Pamięć odpowiedzi żyje tyle co provider, czyli do wylogowania: kolejne konto zaczyna z pustą.
  const [dataCache] = useState(() => createResponseCache(DATA_CACHE_LIMIT));
  const [comparisonCache] = useState(() => createResponseCache(COMPARISON_CACHE_LIMIT));

  const latestRequestRef = useRef(0);
  const latestPageRequestRef = useRef(0);
  // Domyślnie wykresy mają ceny tylko taryfy z profilu; ceny wszystkich taryf operatora potrzebuje Analiza taryf.
  const allTariffsRef = useRef(false);
  const [needsAllTariffs, setNeedsAllTariffs] = useState(false);
  const requireAllTariffs = useCallback((required) => {
    allTariffsRef.current = required;
    setNeedsAllTariffs(required);
  }, []);

  // Odpowiedź na zapytanie wysłane przed wyczyszczeniem pamięci nie może do niej trafić.
  const cacheGenerationRef = useRef(0);
  const clearDataCache = useCallback(() => {
    cacheGenerationRef.current += 1;
    dataCache.clear();
    comparisonCache.clear();
  }, [dataCache, comparisonCache]);

  const invalidateFiles = useCallback(() => {
    clearDataCache();
    setFilesVersion((current) => current + 1);
  }, [clearDataCache]);

  // Stan ustawiany jest dopiero po odpowiedzi API, więc można to wywołać prosto z efektu.
  // Przy błędzie zostaje poprzednio wyświetlona strona.
  const loadFilesPage = useCallback(async (pageToLoad) => {
    const requestId = ++latestPageRequestRef.current;
    try {
      const { data } = await apiClient.get("/energy-files", {
        params: { page: pageToLoad, page_size: PAGE_SIZE },
      });
      if (requestId !== latestPageRequestRef.current) return null;
      setFilesError(null);
      setFiles(data.items);
      setTotal(data.total);
      setPage(data.page);
      setTotalPages(data.total_pages);
      setAggregate(data.aggregate ?? null);
      setDevicesAggregate(data.devices_aggregate ?? null);
      return data.items;
    } catch (error) {
      if (requestId !== latestPageRequestRef.current) return null;
      setFilesError(
        getApiErrorMessage(error, "Nie udało się pobrać listy plików."),
      );
      return null;
    }
  }, []);

  const fetchFilesPage = useCallback(
    async (pageToLoad) => {
      setIsLoadingFiles(true);
      try {
        return await loadFilesPage(pageToLoad);
      } finally {
        setIsLoadingFiles(false);
      }
    },
    [loadFilesPage],
  );

  // Dane podmieniane są dopiero po udanej odpowiedzi - błąd nie kasuje tego,
  // co jest aktualnie wyświetlane. Bez zakresu backend zwraca cały okres pliku.
  // Tryb "profile" ma rachunek taryfy z profilu (Dashboard), a "all" same ceny wszystkich taryf do wykresu
  // (Analiza taryf, kwoty z /tariff-comparison), więc odpowiedzi jednego trybu nie zastępują drugiego.
  const loadFileData = useCallback(
    async (fileId, range, onError) => {
      const requestId = ++latestRequestRef.current;
      const generation = cacheGenerationRef.current;
      const tariffs = allTariffsRef.current ? "all" : "profile";
      setDataError(null);
      setRangeError(null);
      const cached = dataCache.get(dataKey(fileId, range, tariffs));
      if (cached) {
        dataCache.touch(dataKey(fileId, range, tariffs));
        setPendingSource(null);
        setFileData(cached);
        return true;
      }
      setPendingSource({ fileId, range });
      try {
        const { data } = await apiClient.get(`/energy-files/${fileId}/data`, {
          params: { ...(range ? { from: range.from, to: range.to } : {}), tariffs },
        });
        if (generation === cacheGenerationRef.current) dataCache.set(dataKey(fileId, range, tariffs), data);
        if (requestId !== latestRequestRef.current) return false;
        setFileData(data);
        return true;
      } catch (error) {
        if (requestId !== latestRequestRef.current) return false;
        onError(error);
        return false;
      } finally {
        if (requestId === latestRequestRef.current) setPendingSource(null);
      }
    },
    [dataCache],
  );

  // Zmiana pliku zawsze wraca do pełnego okresu - każdy plik ma inny zakres dat.
  const selectFile = useCallback(
    async (fileId) => {
      const loaded = await loadFileData(fileId, null, (error) =>
        setDataError(
          getApiErrorMessage(
            error,
            "Nie udało się pobrać danych wybranego pliku.",
          ),
        ),
      );
      if (loaded) writeStoredFileId(userId, fileId);
      return loaded;
    },
    [loadFileData, userId],
  );

  const selectedFile = fileData?.file ?? null;
  const selectedFileId = selectedFile?.id ?? null;

  const applyDateRange = useCallback(
    (range) => {
      if (!selectedFile) return Promise.resolve(false);
      return loadFileData(selectedFile.id, normalizeRange(range, selectedFile), (error) =>
        setRangeError(
          getApiErrorMessage(
            error,
            "Nie udało się pobrać danych dla wybranego zakresu.",
          ),
        ),
      );
    },
    [loadFileData, selectedFile],
  );

  const selectFirstCompleted = useCallback(
    async (items) => {
      const firstCompleted = items.find((file) => file.status === "completed");
      if (firstCompleted && (await selectFile(firstCompleted.id))) return;
      // Nie ma już żadnego pliku z danymi - nie ma też czego pokazywać.
      setFileData(null);
      setDataError(null);
    },
    [selectFile],
  );

  const initialize = useCallback(async () => {
    const items = await loadFilesPage(1);
    if (items) {
      const storedFileId = readStoredFileId(userId);
      const restored = storedFileId ? await selectFile(storedFileId) : false;
      if (!restored) await selectFirstCompleted(items);
    }
    setIsReady(true);
  }, [loadFilesPage, selectFile, selectFirstCompleted, userId]);

  const deleteFile = useCallback(
    async (fileId) => {
      const deletedFile = files.find((file) => file.id === fileId);
      setDeletingFileId(fileId);
      setDeleteError(null);
      try {
        await apiClient.delete(`/energy-files/${fileId}`);
      } catch (error) {
        setDeleteError(getApiErrorMessage(error, "Nie udało się usunąć pliku."));
        return false;
      } finally {
        setDeletingFileId(null);
      }
      invalidateFiles();

      // Usunięcie jedynego pliku na ostatniej stronie cofa na poprzednią.
      const pageToLoad = files.length === 1 && page > 1 ? page - 1 : page;
      const items = (await loadFilesPage(pageToLoad)) ?? [];

      // Dane zbiorcze zmieniły się, a usunięty plik nie może być dalej wyświetlany.
      const affectedAggregateId = aggregateIdForSourceType(deletedFile?.source_type);
      const aggregateChanged = deletedFile?.status === "completed" && selectedFileId === affectedAggregateId;
      if (selectedFileId === fileId || aggregateChanged) {
        if (!(await selectFile(affectedAggregateId))) await selectFirstCompleted(items);
      }
      return true;
    },
    [files, page, loadFilesPage, selectedFileId, selectFile, selectFirstCompleted, invalidateFiles],
  );

  // Start odroczony do mikrozadania: przy podwójnym montowaniu (StrictMode)
  // pierwsze wywołanie zostaje anulowane i dane pobierane są tylko raz.
  useEffect(() => {
    let cancelled = false;
    Promise.resolve().then(() => {
      if (!cancelled) initialize();
    });
    return () => {
      cancelled = true;
    };
  }, [initialize]);

  const reload = useCallback(async () => {
    invalidateFiles();
    setIsLoadingFiles(true);
    try {
      await initialize();
    } finally {
      setIsLoadingFiles(false);
    }
  }, [initialize, invalidateFiles]);

  const shownRange = normalizeRange(
    fileData?.date_from && fileData?.date_to ? { from: fileData.date_from, to: fileData.date_to } : null,
    selectedFile,
  );
  const shownRangeKey = shownRange ? rangeKey(shownRange) : null;

  // Koszty liczone są przy odczycie z taryfy w profilu: po jego zmianie pobieramy ponownie ten sam plik i zakres.
  const userVersion = useContext(CurrentUserContext)?.version ?? 0;
  const seenUserVersionRef = useRef(null);
  useEffect(() => {
    const previous = seenUserVersionRef.current;
    seenUserVersionRef.current = userVersion;
    if (!previous || previous === userVersion) return;
    clearDataCache();
    if (!selectedFileId) return;
    Promise.resolve().then(() =>
      loadFileData(selectedFileId, rangeFromKey(shownRangeKey), (error) =>
        setDataError(getApiErrorMessage(error, "Nie udało się pobrać danych wybranego pliku.")),
      ),
    );
  }, [userVersion, selectedFileId, shownRangeKey, loadFileData, clearDataCache]);

  // Ekran potrzebuje innego trybu niż wyświetlane dane (wejście na Analizę taryf albo powrót na Dashboard):
  // dociągamy ten sam zakres. Nie w trakcie zapytania, żeby nie zastąpić nowego zakresu starym.
  const shownAllTariffs = fileData?.results?.pricing?.all_tariffs;
  const wrongMode = shownAllTariffs != null && shownAllTariffs !== needsAllTariffs;
  const isPending = pendingSource !== null;
  useEffect(() => {
    if (!wrongMode || isPending || !selectedFileId) return undefined;
    let cancelled = false;
    Promise.resolve().then(() => {
      if (cancelled) return;
      loadFileData(selectedFileId, rangeFromKey(shownRangeKey), (error) =>
        setDataError(getApiErrorMessage(error, "Nie udało się pobrać danych wybranego pliku.")),
      );
    });
    return () => {
      cancelled = true;
    };
  }, [wrongMode, isPending, selectedFileId, shownRangeKey, loadFileData]);

  const reloadData = useCallback(() => {
    const file = fileData?.file;
    if (!file) return Promise.resolve(false);
    const range = normalizeRange({ from: fileData.date_from, to: fileData.date_to }, file);
    return loadFileData(file.id, range, (error) =>
      setDataError(getApiErrorMessage(error, "Nie udało się pobrać danych wybranego pliku.")),
    );
  }, [fileData, loadFileData]);

  // Nowe pliki trafiają na początek listy, więc odświeżenie wraca na 1. stronę.
  const refreshFiles = useCallback(() => {
    invalidateFiles();
    return fetchFilesPage(1);
  }, [fetchFilesPage, invalidateFiles]);

  // Plik i zakres widoku (zapytanie w toku albo wyświetlane dane) oraz zakres ważności odpowiedzi w pamięci.
  const pendingFileId = pendingSource?.fileId ?? null;
  const viewSourceKey = pendingSource
    ? sourceKey(pendingSource)
    : selectedFileId && sourceKey({ fileId: selectedFileId, range: shownRange });
  const viewSource = useMemo(() => (viewSourceKey ? sourceFromKey(viewSourceKey) : null), [viewSourceKey]);
  const cacheScope = `${userId}|${Math.max(userVersion, 1)}|${filesVersion}`;

  const value = useMemo(
    () => ({
      files,
      total,
      page,
      totalPages,
      isLoadingFiles,
      filesError,
      goToPage: fetchFilesPage,
      refreshFiles,
      reload,
      aggregate,
      devicesAggregate,
      deleteFile,
      deletingFileId,
      deleteError,
      clearDeleteError: () => setDeleteError(null),

      selectedFile,
      selectedFileId,
      results: fileData?.results ?? null,
      pendingFileId,
      isLoadingData: pendingFileId !== null,
      dataError,
      clearDataError: () => setDataError(null),
      selectFile,

      dateRange:
        fileData?.date_from && fileData?.date_to
          ? { from: fileData.date_from, to: fileData.date_to }
          : null,
      applyDateRange,
      rangeError,
      clearRangeError: () => setRangeError(null),
      requireAllTariffs,
      reloadData,

      viewSource,
      cacheScope,
      comparisonCache,

      isReady,
    }),
    [
      aggregate,
      devicesAggregate,
      deleteFile,
      deletingFileId,
      deleteError,
      selectedFile,
      selectedFileId,
      applyDateRange,
      rangeError,
      files,
      total,
      page,
      totalPages,
      isLoadingFiles,
      filesError,
      fetchFilesPage,
      refreshFiles,
      reload,
      fileData,
      pendingFileId,
      dataError,
      selectFile,
      requireAllTariffs,
      reloadData,
      viewSource,
      cacheScope,
      comparisonCache,
      isReady,
    ],
  );

  return (
    <EnergyFileContext.Provider value={value}>
      {children}
    </EnergyFileContext.Provider>
  );
}
