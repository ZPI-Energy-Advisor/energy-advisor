import { useCallback, useEffect, useId, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { FiCalendar, FiCheck, FiChevronDown, FiFileText, FiLayers } from "react-icons/fi";
import { useEnergyFiles } from "../hooks/useEnergyFiles";
import { useRangeBounds } from "../hooks/useRangeBounds";
import SourceTypeBadge from "./SourceTypeBadge";
import DateRangeForm from "./DateRangeForm";
import {
  FILES_TABLE_ANCHOR,
  countDays,
  formatDataResolution,
  formatDate,
  formatDateRange,
  formatFilesCount,
  formatRecordsCount,
  isAggregateSource,
  isSameRange,
} from "../utils/energyFiles";

const PILL =
  "inline-flex max-w-full items-center gap-2 rounded-full border bg-white px-3 py-1.5 text-sm shadow-sm transition-colors " +
  "focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500";
// Na telefonie panel od lewej krawędzi przycisku, od sm przy prawej (pigułki stoją po prawej stronie nagłówka);
// szerokość nie wychodzi poza ekran ani pod menu boczne (16rem od md).
const PANEL =
  "absolute left-0 sm:left-auto sm:right-0 top-full z-30 mt-2 w-[30rem] max-w-[calc(100vw-2rem)] " +
  "md:max-w-[calc(100vw-20rem)] rounded-xl border border-gray-200 bg-white p-4 shadow-lg";

const fileDetails = (file, results) =>
  [
    formatDateRange(file),
    file.days_count != null && `${file.days_count} dni`,
    file.records_count != null && formatRecordsCount(file.records_count, file.source_type),
    isAggregateSource(file.id) && formatFilesCount(file.files_count),
    formatDataResolution(results?.statistics),
  ].filter(Boolean);

function Notice({ tone = "error", children, onClose }) {
  const colors = tone === "error" ? "text-red-600 bg-red-50" : "text-amber-800 bg-amber-50";
  return (
    <div className={`mt-2 flex items-start justify-between gap-3 rounded-lg p-3 text-sm ${colors}`}>
      <span>{children}</span>
      {onClose && (
        <button type="button" onClick={onClose} className="shrink-0 font-medium hover:underline" aria-label="Zamknij komunikat">
          ✕
        </button>
      )}
    </div>
  );
}

function SourceOption({ source, isSelected, onPick }) {
  const Icon = isAggregateSource(source.id) ? FiLayers : FiFileText;
  return (
    <li>
      <button
        type="button"
        onClick={() => onPick(source.id)}
        aria-current={isSelected ? "true" : undefined}
        className={`flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm transition-colors ${
          isSelected ? "bg-emerald-50 text-emerald-900" : "hover:bg-gray-50"
        }`}
      >
        <Icon aria-hidden="true" className="shrink-0 text-emerald-600" />
        <span className="min-w-0 flex-1">
          <span className="block truncate font-medium">{source.file_name}</span>
          <span className="block text-xs text-gray-500">{formatDateRange(source)}</span>
        </span>
        <SourceTypeBadge sourceType={source.source_type} />
        {isSelected && <FiCheck aria-label="Wyświetlany" className="shrink-0 text-emerald-600" />}
      </button>
    </li>
  );
}

function FilePanel({ id, onClose }) {
  const { selectedFile, selectedFileId, results, files, total, aggregate, devicesAggregate, selectFile } = useEnergyFiles();
  const aggregates = [aggregate, devicesAggregate].filter(Boolean);
  const completed = files.filter((file) => file.status === "completed");
  const pick = (sourceId) => {
    if (sourceId !== selectedFileId) selectFile(sourceId);
    onClose();
  };

  return (
    <div id={id} role="dialog" aria-label="Wybór danych" className={PANEL}>
      <p className="text-xs font-medium uppercase tracking-wide text-gray-500">Wyświetlane dane</p>
      <p className="mt-1 break-all text-sm font-semibold text-gray-900">{selectedFile.file_name}</p>
      <p className="mt-0.5 text-xs text-gray-500">{fileDetails(selectedFile, results).join(" · ")}</p>

      <ul className="mt-3 max-h-72 space-y-1 overflow-y-auto border-t border-gray-100 pt-3">
        {[...aggregates, ...completed].map((source) => (
          <SourceOption key={source.id} source={source} isSelected={source.id === selectedFileId} onPick={pick} />
        ))}
      </ul>
      <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-gray-100 pt-3 text-xs text-gray-500">
        <span>{total > files.length ? `Ostatnie ${files.length} z ${total} plików.` : ""}</span>
        <Link to={`/upload#${FILES_TABLE_ANCHOR}`} onClick={onClose} className="font-medium text-emerald-700 hover:underline">
          Wszystkie pliki i import
        </Link>
      </div>
    </div>
  );
}

// Nagłówek ekranu: tytuł po lewej, a po prawej z jakiego pliku i okresu są dane. Wybór pliku i okresu
// otwiera się w panelu po kliknięciu, żeby kontrolki nie zajmowały miejsca, a kontekst był zawsze widoczny.
// Na wąskim ekranie pigułki przechodzą pod tytuł; `subtitle` (opis ekranu) idzie pod nimi na całą szerokość.
// `showRange={false}`: ekran z własnym wyborem okresu (np. optymalizacja) albo bez danych w pliku.
function DataContextBar({ title, subtitle, showRange = true }) {
  const {
    selectedFile, dateRange, isLoadingData, dataError, clearDataError, rangeError, clearRangeError,
  } = useEnergyFiles();
  const bounds = useRangeBounds();
  const [open, setOpen] = useState(null);
  const barRef = useRef(null);
  const fileTrigger = useRef(null);
  const rangeTrigger = useRef(null);
  const fileId = useId();
  const rangeId = useId();

  const close = useCallback(() => setOpen(null), []);

  useEffect(() => {
    if (!open) return undefined;
    const panel = document.getElementById(open === "file" ? fileId : rangeId);
    panel?.querySelector("button, input, select, a")?.focus();
    const onKey = (event) => {
      if (event.key !== "Escape") return;
      setOpen(null);
      (open === "file" ? fileTrigger : rangeTrigger).current?.focus();
    };
    const onPointer = (event) => {
      if (!barRef.current?.contains(event.target)) setOpen(null);
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onPointer);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onPointer);
    };
  }, [open, fileId, rangeId]);

  const heading = <h2 className="text-xl font-bold text-gray-900">{title}</h2>;
  const description = subtitle && <p className="mt-2 text-sm text-gray-500">{subtitle}</p>;
  if (!selectedFile) {
    return (
      <div className="mb-6 border-b border-gray-200 pb-4 md:mb-8">
        {heading}
        {description}
      </div>
    );
  }

  const toggle = (name) => setOpen((current) => (current === name ? null : name));
  const pillClass = (name) => `${PILL} ${open === name ? "border-emerald-500" : "border-gray-200 hover:border-emerald-300"}`;
  const isAggregate = isAggregateSource(selectedFile.id);
  const FileIcon = isAggregate ? FiLayers : FiFileText;
  const hasRange = showRange && bounds && dateRange;
  const skippedFiles = isAggregate ? selectedFile.skipped_files ?? [] : [];
  const wholePeriod = hasRange && isSameRange(dateRange, bounds);

  return (
    <div className="mb-6 md:mb-8">
      <div className="border-b border-gray-200 pb-4">
        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-3">
          {heading}
          <div ref={barRef} className="flex min-w-0 flex-wrap items-center gap-2 sm:justify-end">
            <div className="relative max-w-full">
              <button
                ref={fileTrigger}
                type="button"
                onClick={() => toggle("file")}
                aria-expanded={open === "file"}
                aria-controls={fileId}
                aria-label={`Dane z: ${selectedFile.file_name}. Zmień plik`}
                className={pillClass("file")}
              >
                <FileIcon aria-hidden="true" className="shrink-0 text-emerald-600" />
                <span className="truncate font-semibold text-gray-900 max-w-[14rem] sm:max-w-[16rem]" title={selectedFile.file_name}>
                  {selectedFile.file_name}
                </span>
                <SourceTypeBadge sourceType={selectedFile.source_type} />
                <FiChevronDown aria-hidden="true" className="shrink-0 text-gray-400" />
              </button>
              {open === "file" && <FilePanel id={fileId} onClose={close} />}
            </div>

            {hasRange && (
              <div className="relative max-w-full">
                <button
                  ref={rangeTrigger}
                  type="button"
                  onClick={() => toggle("range")}
                  aria-expanded={open === "range"}
                  aria-controls={rangeId}
                  aria-label={`Okres: ${formatDate(dateRange.from)} – ${formatDate(dateRange.to)}, ${countDays(dateRange)} dni${wholePeriod ? ", cały okres" : ""}. Zmień okres`}
                  title={wholePeriod ? "Cały okres danych" : undefined}
                  className={pillClass("range")}
                >
                  <FiCalendar aria-hidden="true" className="shrink-0 text-emerald-600" />
                  <span className="font-semibold text-gray-900">
                    {formatDate(dateRange.from)} – {formatDate(dateRange.to)}
                  </span>
                  <span className="whitespace-nowrap text-gray-500">· {countDays(dateRange)} dni</span>
                  <FiChevronDown aria-hidden="true" className="shrink-0 text-gray-400" />
                </button>
                {open === "range" && (
                  <div id={rangeId} role="dialog" aria-label="Wybór okresu" className={PANEL}>
                    <DateRangeForm
                      key={`${selectedFile.id}:${dateRange.from}:${dateRange.to}`}
                      bounds={bounds}
                      appliedRange={dateRange}
                        onApplied={close}
                    />
                  </div>
                )}
              </div>
            )}

            {isLoadingData && (
              <span role="status" className="text-xs text-emerald-600">
                Ładowanie...
              </span>
            )}
          </div>
        </div>
        {description}
      </div>

      {skippedFiles.length > 0 && (
        <Notice tone="warning">
          Pominięto {formatFilesCount(skippedFiles.length)} wgrane przed wprowadzeniem łączenia danych:{" "}
          {skippedFiles.map((file) => file.file_name).join(", ")}. Wgraj je ponownie, aby uwzględnić ich dane.
        </Notice>
      )}
      {dataError && (
        <Notice onClose={clearDataError}>{dataError} Wyświetlane są nadal dane poprzednio wybranego pliku.</Notice>
      )}
      {rangeError && (
        <Notice onClose={clearRangeError}>{rangeError} Wyświetlane są nadal dane poprzedniego zakresu.</Notice>
      )}
    </div>
  );
}

export default DataContextBar;
