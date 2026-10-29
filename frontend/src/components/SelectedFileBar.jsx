import { Link } from "react-router-dom";
import { FiFileText, FiLayers } from "react-icons/fi";
import { useEnergyFiles } from "../hooks/useEnergyFiles";
import SourceTypeBadge from "./SourceTypeBadge";
import {
  FILES_TABLE_ANCHOR,
  formatDataResolution,
  formatDateRange,
  formatFilesCount,
  formatRecordsCount,
  isAggregateSource,
} from "../utils/energyFiles";

// Pokazuje, z którego pliku pochodzą wyświetlane dane. Sam wybór odbywa się
// w tabeli "Twoje pliki" na stronie importu.
function SelectedFileBar() {
  const { selectedFile, results, isLoadingData, dataError, clearDataError } = useEnergyFiles();

  if (!selectedFile) return null;

  const isAggregate = isAggregateSource(selectedFile.id);
  const details = [
    formatDateRange(selectedFile),
    selectedFile.days_count != null && `${selectedFile.days_count} dni`,
    selectedFile.records_count != null && formatRecordsCount(selectedFile.records_count, selectedFile.source_type),
    isAggregate && formatFilesCount(selectedFile.files_count),
    formatDataResolution(results?.statistics),
  ].filter(Boolean);
  const skippedFiles = isAggregate ? selectedFile.skipped_files ?? [] : [];

  return (
    <div className="mb-6 md:mb-8">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm bg-white border border-gray-100 rounded-lg shadow-sm px-4 py-3">
        {isAggregate ? (
          <FiLayers className="text-emerald-600 shrink-0" />
        ) : (
          <FiFileText className="text-emerald-600 shrink-0" />
        )}
        <span className="text-gray-500">Dane z:</span>
        <span className="font-bold text-gray-900 truncate max-w-full" title={selectedFile.file_name}>
          {selectedFile.file_name}
        </span>
        <SourceTypeBadge sourceType={selectedFile.source_type} />
        <span className="text-gray-500">{details.join(" · ")}</span>
        {isLoadingData && <span className="text-emerald-600 text-xs">Ładowanie...</span>}
        <Link
          to={`/upload#${FILES_TABLE_ANCHOR}`}
          className="ml-auto font-medium text-emerald-700 hover:underline"
        >
          Zmień
        </Link>
      </div>

      {skippedFiles.length > 0 && (
        <p className="mt-2 p-3 text-sm text-amber-800 bg-amber-50 rounded-lg">
          Pominięto {formatFilesCount(skippedFiles.length)} wgrane przed wprowadzeniem łączenia danych:{" "}
          {skippedFiles.map((file) => file.file_name).join(", ")}. Wgraj je ponownie, aby uwzględnić ich dane.
        </p>
      )}

      {dataError && (
        <div className="mt-2 p-3 text-sm text-red-600 bg-red-50 rounded-lg flex items-start justify-between gap-3">
          <span>{dataError} Wyświetlane są nadal dane poprzednio wybranego pliku.</span>
          <button type="button" onClick={clearDataError} className="font-medium hover:underline shrink-0" aria-label="Zamknij komunikat">
            ✕
          </button>
        </div>
      )}
    </div>
  );
}

export default SelectedFileBar;
