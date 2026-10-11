import { useMemo, useState } from "react";
import { FiCalendar } from "react-icons/fi";
import { useEnergyFiles } from "../hooks/useEnergyFiles";
import {
  buildQuickRanges,
  countDays,
  formatDate,
  isSameRange,
  validateDateRange,
} from "../utils/energyFiles";

const inputClass =
  "w-full sm:w-auto bg-gray-50 border text-gray-900 text-sm rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:border-emerald-500";

const quickButtonClass = (isActive) =>
  `px-3 py-2 text-xs md:text-sm font-medium rounded-lg border transition-colors whitespace-nowrap ${
    isActive
      ? "bg-emerald-50 border-emerald-500 text-emerald-700"
      : "bg-white border-gray-200 text-gray-600 hover:border-emerald-300 hover:text-emerald-700"
  }`;

function QuickRangeSelect({ label, options, appliedRange, onSelect, disabled }) {
  const activeIndex = options.findIndex((option) => isSameRange(option, appliedRange));

  return (
    <select
      aria-label={label}
      value={activeIndex === -1 ? "" : String(activeIndex)}
      onChange={(e) => e.target.value !== "" && onSelect(options[Number(e.target.value)])}
      disabled={disabled}
      className={`${quickButtonClass(activeIndex !== -1)} cursor-pointer disabled:opacity-60`}
    >
      <option value="" disabled>
        {label}
      </option>
      {options.map((option, index) => (
        <option key={option.label} value={index}>
          {option.label}
        </option>
      ))}
    </select>
  );
}

// Szkic zakresu żyje lokalnie; wykresy zmieniają się dopiero po zatwierdzeniu.
function DateRangeForm({ bounds, appliedRange }) {
  const { applyDateRange, isLoadingData, rangeError, clearRangeError } = useEnergyFiles();
  const [draft, setDraft] = useState(appliedRange);

  const { months, quarters } = useMemo(() => buildQuickRanges(bounds), [bounds]);
  const validationError = validateDateRange(draft, bounds);
  const canApply = !validationError && !isLoadingData && !isSameRange(draft, appliedRange);
  const isWholePeriod = isSameRange(appliedRange, bounds);

  const apply = (range) => {
    setDraft(range);
    if (!isSameRange(range, appliedRange)) applyDateRange(range);
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    if (canApply) applyDateRange(draft);
  };

  return (
    <div className="mb-6 md:mb-8 bg-white border border-gray-100 rounded-lg shadow-sm px-4 py-4">
      <form
        onSubmit={handleSubmit}
        noValidate
        className="flex flex-col lg:flex-row lg:items-end gap-3 lg:gap-4"
      >
        <div className="flex flex-col sm:flex-row sm:items-end gap-3">
          <label className="flex flex-col gap-1 text-xs font-medium text-gray-500">
            Data od
            <input
              type="date"
              value={draft.from}
              min={bounds.from}
              max={bounds.to}
              onChange={(e) => setDraft((prev) => ({ ...prev, from: e.target.value }))}
              aria-invalid={Boolean(validationError)}
              className={`${inputClass} ${validationError ? "border-red-300" : "border-gray-200"}`}
            />
          </label>
          <label className="flex flex-col gap-1 text-xs font-medium text-gray-500">
            Data do
            <input
              type="date"
              value={draft.to}
              min={bounds.from}
              max={bounds.to}
              onChange={(e) => setDraft((prev) => ({ ...prev, to: e.target.value }))}
              aria-invalid={Boolean(validationError)}
              className={`${inputClass} ${validationError ? "border-red-300" : "border-gray-200"}`}
            />
          </label>
          <button
            type="submit"
            disabled={!canApply}
            className="bg-emerald-600 text-white text-sm font-medium px-5 py-2 rounded-lg hover:bg-emerald-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Zastosuj
          </button>
        </div>

        <div className="flex flex-wrap items-center gap-2 lg:ml-auto">
          <span className="text-xs font-medium text-gray-500 w-full sm:w-auto">Szybki wybór:</span>
          <QuickRangeSelect
            label="Miesiąc"
            options={months}
            appliedRange={appliedRange}
            onSelect={apply}
            disabled={isLoadingData}
          />
          <QuickRangeSelect
            label="Kwartał"
            options={quarters}
            appliedRange={appliedRange}
            onSelect={apply}
            disabled={isLoadingData}
          />
          <button
            type="button"
            onClick={() => apply(bounds)}
            disabled={isLoadingData}
            className={`${quickButtonClass(isWholePeriod)} disabled:opacity-60`}
          >
            Cały okres
          </button>
        </div>
      </form>

      <div className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs md:text-sm text-gray-500">
        <FiCalendar className="text-emerald-600 shrink-0" />
        <span>
          Wyświetlany okres:{" "}
          <span className="font-semibold text-gray-800">
            {formatDate(appliedRange.from)} – {formatDate(appliedRange.to)}
          </span>{" "}
          ({countDays(appliedRange)} dni{isWholePeriod ? ", cały okres danych" : ""})
        </span>
        {isLoadingData && <span className="text-emerald-600 text-xs">Przeliczanie...</span>}
      </div>

      {validationError && (
        <p role="alert" className="mt-2 text-sm text-red-600">
          {validationError}
        </p>
      )}

      {rangeError && (
        <div className="mt-2 p-3 text-sm text-red-600 bg-red-50 rounded-lg flex items-start justify-between gap-3">
          <span>{rangeError} Wyświetlane są nadal dane poprzedniego zakresu.</span>
          <button
            type="button"
            onClick={clearRangeError}
            className="font-medium hover:underline shrink-0"
            aria-label="Zamknij komunikat"
          >
            ✕
          </button>
        </div>
      )}
    </div>
  );
}

function DateRangeFilter() {
  const { selectedFile, dateRange } = useEnergyFiles();
  const dataStart = selectedFile?.data_start;
  const dataEnd = selectedFile?.data_end;
  const bounds = useMemo(
    () => (dataStart && dataEnd ? { from: dataStart, to: dataEnd } : null),
    [dataStart, dataEnd],
  );

  if (!bounds || !dateRange) return null;

  // Nowy plik lub nowo zastosowany zakres resetuje szkic w formularzu.
  return (
    <DateRangeForm
      key={`${selectedFile.id}:${dateRange.from}:${dateRange.to}`}
      bounds={bounds}
      appliedRange={dateRange}
    />
  );
}

export default DateRangeFilter;
