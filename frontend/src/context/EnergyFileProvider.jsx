import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import apiClient from "../api/client";
import { EnergyFileContext } from "./energyFileContext";
import { aggregateIdForSourceType, getApiErrorMessage } from "../utils/energyFiles";

const PAGE_SIZE = 20;

const getStoredUserId = () => {
  try {
    return JSON.parse(localStorage.getItem("user"))?.id ?? null;
  } catch {
    return null;
  }
};

// Klucz zależy od użytkownika, żeby po zmianie konta nie podpowiadać cudzego wyboru.
const storageKey = (userId) => `selected_energy_file:${userId}`;

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
  const [pendingFileId, setPendingFileId] = useState(null);
  const [dataError, setDataError] = useState(null);
  const [rangeError, setRangeError] = useState(null);
  const [isReady, setIsReady] = useState(false);

  const latestRequestRef = useRef(0);
  const latestPageRequestRef = useRef(0);

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
  const loadFileData = useCallback(async (fileId, range, onError) => {
    const requestId = ++latestRequestRef.current;
    setPendingFileId(fileId);
    setDataError(null);
    setRangeError(null);
    try {
      const { data } = await apiClient.get(`/energy-files/${fileId}/data`, {
        params: range ? { from: range.from, to: range.to } : undefined,
      });
      if (requestId !== latestRequestRef.current) return false;
      setFileData(data);
      return true;
    } catch (error) {
      if (requestId !== latestRequestRef.current) return false;
      onError(error);
      return false;
    } finally {
      if (requestId === latestRequestRef.current) setPendingFileId(null);
    }
  }, []);

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

  const selectedFileId = fileData?.file?.id ?? null;

  const applyDateRange = useCallback(
    (range) => {
      if (!selectedFileId) return Promise.resolve(false);
      return loadFileData(selectedFileId, range, (error) =>
        setRangeError(
          getApiErrorMessage(
            error,
            "Nie udało się pobrać danych dla wybranego zakresu.",
          ),
        ),
      );
    },
    [loadFileData, selectedFileId],
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
    [files, page, loadFilesPage, selectedFileId, selectFile, selectFirstCompleted],
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
    setIsLoadingFiles(true);
    try {
      await initialize();
    } finally {
      setIsLoadingFiles(false);
    }
  }, [initialize]);

  // Nowe pliki trafiają na początek listy, więc odświeżenie wraca na 1. stronę.
  const refreshFiles = useCallback(() => fetchFilesPage(1), [fetchFilesPage]);

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

      selectedFile: fileData?.file ?? null,
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

      isReady,
    }),
    [
      aggregate,
      devicesAggregate,
      deleteFile,
      deletingFileId,
      deleteError,
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
      isReady,
    ],
  );

  return (
    <EnergyFileContext.Provider value={value}>
      {children}
    </EnergyFileContext.Provider>
  );
}
