export const FILES_TABLE_ANCHOR = "pliki";

export const formatDate = (isoDate) => {
  if (!isoDate) return "";
  const [year, month, day] = isoDate.slice(0, 10).split("-");
  return `${day}.${month}.${year}`;
};

export const formatDateRange = (file) => {
  if (!file?.data_start || !file?.data_end) return "Brak zakresu dat";
  return `${formatDate(file.data_start)} – ${formatDate(file.data_end)}`;
};

export const FILE_STATUS_LABELS = {
  completed: "Gotowy",
  processing: "Przetwarzanie",
  failed: "Błąd przetwarzania",
};

// Taryfa preferowana przez użytkownika, o ile występuje w wynikach pliku;
// w przeciwnym razie pierwsza dostępna.
export const resolveTariffName = (tariffs, preferredName) => {
  if (!tariffs) return null;
  if (preferredName && tariffs[preferredName]) return preferredName;
  return Object.keys(tariffs)[0] ?? null;
};

export const getApiErrorMessage = (error, fallback) => {
  const detail = error?.response?.data?.detail;
  return typeof detail === "string" ? detail : fallback;
};
