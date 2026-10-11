import { useEffect, useRef } from "react";
import { useLocation } from "react-router-dom";
import { FiChevronLeft, FiChevronRight, FiLayers, FiRefreshCw, FiTrash2 } from "react-icons/fi";
import { useEnergyFiles } from "../hooks/useEnergyFiles";
import {
  ALL_FILES_ID,
  FILE_STATUS_LABELS,
  FILES_TABLE_ANCHOR,
  formatDateRange,
  pluralizeFiles,
} from "../utils/energyFiles";

function Spinner({ className = "" }) {
  return (
    <svg className={`animate-spin h-4 w-4 ${className}`} fill="none" viewBox="0 0 24 24">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
      <path
        className="opacity-75"
        fill="currentColor"
        d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
      ></path>
    </svg>
  );
}

const formatUploadDate = (isoDateTime) =>
  // Backend zwraca czas UTC bez strefy - dopisujemy "Z", żeby pokazać czas lokalny.
  new Date(isoDateTime.endsWith("Z") ? isoDateTime : `${isoDateTime}Z`).toLocaleString("pl-PL", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });

const headerClass =
  "px-4 md:px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider whitespace-nowrap";

function EnergyFilesTable() {
  const {
    files,
    total,
    page,
    totalPages,
    isLoadingFiles,
    filesError,
    goToPage,
    reload,
    selectedFileId,
    pendingFileId,
    dataError,
    clearDataError,
    selectFile,
    isReady,
    aggregate,
    deleteFile,
    deletingFileId,
    deleteError,
    clearDeleteError,
  } = useEnergyFiles();

  const handleDelete = (file) => {
    const message = `Usunąć plik „${file.file_name}”? Jego dane znikną także z widoku „Wszystkie pliki”. Tej operacji nie można cofnąć.`;
    if (window.confirm(message)) deleteFile(file.id);
  };

  const renderSelectAction = (sourceId, isSelected) => {
    if (sourceId === pendingFileId) return <Spinner className="text-emerald-600 inline-block" />;
    if (isSelected) {
      return (
        <span className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-bold bg-emerald-100 text-emerald-800 border border-emerald-200 whitespace-nowrap">
          Wyświetlany
        </span>
      );
    }
    return (
      <button
        type="button"
        onClick={(event) => {
          event.stopPropagation();
          selectFile(sourceId);
        }}
        className="px-3 py-1.5 text-xs font-medium rounded-md border border-emerald-200 text-emerald-700 hover:bg-emerald-50 transition-colors"
      >
        Wybierz
      </button>
    );
  };

  const renderAggregateRow = () => {
    const isSelected = selectedFileId === ALL_FILES_ID;
    const dateRange = formatDateRange(aggregate);
    const filesLabel = `łączne dane z ${aggregate.files_count} ${pluralizeFiles(aggregate.files_count)}`;

    return (
      <tr
        onClick={() => !isSelected && selectFile(ALL_FILES_ID)}
        aria-selected={isSelected}
        className={`text-sm border-b-2 border-gray-200 ${isSelected ? "bg-emerald-50" : "bg-gray-50/60 hover:bg-gray-50 cursor-pointer transition-colors"}`}
      >
        <td className="px-4 md:px-6 py-3 md:py-4">
          <span className={`flex items-center gap-2 font-bold ${isSelected ? "text-emerald-800" : "text-gray-900"}`}>
            <FiLayers className="text-emerald-600 shrink-0" /> {aggregate.file_name}
          </span>
          <span className="block text-xs text-gray-500 truncate">
            <span className="lg:hidden">{dateRange} · </span>
            {filesLabel}
          </span>
        </td>
        <td className="hidden lg:table-cell px-4 md:px-6 py-3 md:py-4 whitespace-nowrap">{dateRange}</td>
        <td className="hidden sm:table-cell px-4 md:px-6 py-3 md:py-4 whitespace-nowrap text-right text-gray-400">–</td>
        <td className="hidden xl:table-cell px-4 md:px-6 py-3 md:py-4 whitespace-nowrap text-gray-500">automatycznie</td>
        <td className="px-4 md:px-6 py-3 md:py-4 text-right">{renderSelectAction(ALL_FILES_ID, isSelected)}</td>
      </tr>
    );
  };

  const location = useLocation();
  const sectionRef = useRef(null);

  // Link "Zmień" z Dashboardu/wyników prowadzi tutaj z kotwicą #pliki.
  useEffect(() => {
    if (location.hash === `#${FILES_TABLE_ANCHOR}`) {
      sectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [location.hash]);

  const renderBody = () => {
    if (!isReady) {
      return <p className="px-4 md:px-6 py-8 text-center text-gray-500 text-sm">Ładowanie plików...</p>;
    }

    if (files.length === 0) {
      return filesError ? (
        <div className="px-4 md:px-6 py-8 text-center text-sm">
          <p className="text-red-600 mb-3">{filesError}</p>
          <button
            type="button"
            onClick={reload}
            disabled={isLoadingFiles}
            className="inline-flex items-center gap-2 font-medium text-emerald-700 hover:underline disabled:opacity-60"
          >
            <FiRefreshCw /> {isLoadingFiles ? "Ładowanie..." : "Spróbuj ponownie"}
          </button>
        </div>
      ) : (
        <p className="px-4 md:px-6 py-8 text-center text-gray-500 text-sm">
          Nie masz jeszcze żadnych plików. Wgraj pierwszy plik CSV powyżej.
        </p>
      );
    }

    return (
      <div className={`transition-opacity ${isLoadingFiles ? "opacity-60" : ""}`}>
        {/* table-fixed + stałe szerokości kolumn: tabela zawsze mieści się w karcie,
            a mniej ważne kolumny na węższych ekranach przechodzą pod nazwę pliku. */}
        <table className="w-full table-fixed divide-y divide-gray-200">
          <thead className="bg-gray-50">
            <tr>
              <th scope="col" className={headerClass}>Plik</th>
              <th scope="col" className={`${headerClass} hidden lg:table-cell w-52`}>Zakres danych</th>
              <th scope="col" className={`${headerClass} hidden sm:table-cell w-24 text-right`}>Rekordy</th>
              <th scope="col" className={`${headerClass} hidden xl:table-cell w-40`}>Import</th>
              <th scope="col" className={`${headerClass} w-36 md:w-44`} aria-label="Akcja"></th>
            </tr>
          </thead>
          <tbody className="bg-white divide-y divide-gray-200">
            {aggregate && renderAggregateRow()}
            {files.map((file) => {
              const isSelected = file.id === selectedFileId;
              const isAvailable = file.status === "completed";
              const isDeleting = file.id === deletingFileId;
              const dateRange = isAvailable ? formatDateRange(file) : "–";

              return (
                <tr
                  key={file.id}
                  onClick={() => isAvailable && !isSelected && selectFile(file.id)}
                  aria-selected={isSelected}
                  className={`text-sm ${
                    isSelected
                      ? "bg-emerald-50"
                      : isAvailable
                        ? "hover:bg-gray-50 cursor-pointer transition-colors"
                        : "text-gray-400"
                  }`}
                >
                  <td className="px-4 md:px-6 py-3 md:py-4">
                    <span
                      className={`block truncate font-medium ${isSelected ? "text-emerald-800" : isAvailable ? "text-gray-900" : ""}`}
                      title={file.file_name}
                    >
                      {file.file_name}
                    </span>
                    <span className="block text-xs text-gray-500 xl:hidden truncate">
                      <span className="lg:hidden">{dateRange} · </span>
                      <span className="sm:hidden">{file.records_count ?? "–"} rek. · </span>
                      import {formatUploadDate(file.uploaded_at)}
                    </span>
                  </td>
                  <td className="hidden lg:table-cell px-4 md:px-6 py-3 md:py-4 whitespace-nowrap">
                    {dateRange}
                  </td>
                  <td className="hidden sm:table-cell px-4 md:px-6 py-3 md:py-4 whitespace-nowrap text-right">
                    {file.records_count ?? "–"}
                  </td>
                  <td className="hidden xl:table-cell px-4 md:px-6 py-3 md:py-4 whitespace-nowrap text-gray-500">
                    {formatUploadDate(file.uploaded_at)}
                  </td>
                  <td className="px-4 md:px-6 py-3 md:py-4">
                    <div className="flex items-center justify-end gap-1.5 md:gap-2">
                      {isAvailable ? (
                        renderSelectAction(file.id, isSelected)
                      ) : (
                        <span
                          className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-red-50 text-red-700 border border-red-100 cursor-help text-center"
                          title={file.error_message || undefined}
                        >
                          {FILE_STATUS_LABELS[file.status] || file.status}
                        </span>
                      )}
                      {isDeleting ? (
                        <Spinner className="text-red-500 shrink-0" />
                      ) : (
                        <button
                          type="button"
                          onClick={(event) => {
                            event.stopPropagation();
                            handleDelete(file);
                          }}
                          disabled={deletingFileId !== null}
                          className="p-1.5 rounded-md text-gray-400 hover:text-red-600 hover:bg-red-50 transition-colors disabled:opacity-40 shrink-0"
                          title="Usuń plik"
                          aria-label={`Usuń plik ${file.file_name}`}
                        >
                          <FiTrash2 />
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    );
  };

  return (
    <section
      ref={sectionRef}
      id={FILES_TABLE_ANCHOR}
      className="mt-8 bg-white border border-gray-200 rounded-lg shadow-sm overflow-hidden scroll-mt-4"
    >
      <div className="px-4 md:px-6 py-4 border-b border-gray-200 flex flex-col sm:flex-row sm:items-center justify-between gap-2">
        <div>
          <h3 className="font-bold text-gray-900">Twoje pliki</h3>
          <p className="text-xs md:text-sm text-gray-500">
            Wybierz pojedynczy plik albo „Wszystkie pliki”, aby zobaczyć dane na Dashboardzie i w analizie taryf. Przy nakładających się okresach liczy się nowszy import.
          </p>
        </div>
      </div>

      {dataError && (
        <div className="mx-4 md:mx-6 mt-4 p-3 text-sm text-red-600 bg-red-50 rounded-lg flex items-start justify-between gap-3">
          <span>
            {dataError}
            {selectedFileId && " Wyświetlane są nadal dane poprzednio wybranego pliku."}
          </span>
          <button type="button" onClick={clearDataError} className="font-medium hover:underline shrink-0" aria-label="Zamknij komunikat">
            ✕
          </button>
        </div>
      )}

      {deleteError && (
        <div className="mx-4 md:mx-6 mt-4 p-3 text-sm text-red-600 bg-red-50 rounded-lg flex items-start justify-between gap-3">
          <span>{deleteError}</span>
          <button type="button" onClick={clearDeleteError} className="font-medium hover:underline shrink-0" aria-label="Zamknij komunikat">
            ✕
          </button>
        </div>
      )}

      {filesError && files.length > 0 && (
        <div className="mx-4 md:mx-6 mt-4 p-3 text-sm text-red-600 bg-red-50 rounded-lg">
          {filesError}
        </div>
      )}

      {renderBody()}

      {totalPages > 1 && (
        <div className="px-4 md:px-6 py-3 border-t border-gray-200 flex items-center justify-between gap-3 text-sm">
          <span className="text-gray-500">
            Strona {page} z {totalPages} · {total} plików
          </span>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => goToPage(page - 1)}
              disabled={page <= 1 || isLoadingFiles}
              className="inline-flex items-center gap-1 px-3 py-1.5 rounded-md border border-gray-200 text-gray-700 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <FiChevronLeft /> Poprzednia
            </button>
            <button
              type="button"
              onClick={() => goToPage(page + 1)}
              disabled={page >= totalPages || isLoadingFiles}
              className="inline-flex items-center gap-1 px-3 py-1.5 rounded-md border border-gray-200 text-gray-700 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              Następna <FiChevronRight />
            </button>
          </div>
        </div>
      )}
    </section>
  );
}

export default EnergyFilesTable;
