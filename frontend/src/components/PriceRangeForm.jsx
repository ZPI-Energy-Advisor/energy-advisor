import { useMemo, useState } from "react";
import { isSameRange, validateDateRange } from "../utils/energyFiles";
import { buildPriceQuickRanges } from "../utils/dynamicPrices";

const inputClass =
  "w-full sm:w-auto bg-gray-50 border text-gray-900 text-sm rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:border-emerald-500";

const quickButtonClass = (isActive) =>
  `px-3 py-2 text-xs md:text-sm font-medium rounded-lg border transition-colors whitespace-nowrap disabled:opacity-60 ${
    isActive
      ? "bg-emerald-50 border-emerald-500 text-emerald-700"
      : "bg-white border-gray-200 text-gray-600 hover:border-emerald-300 hover:text-emerald-700"
  }`;

function PriceRangeForm({ bounds, appliedRange, onApply, isLoading }) {
  const [draft, setDraft] = useState(appliedRange);
  const quickRanges = useMemo(() => buildPriceQuickRanges(bounds), [bounds]);

  const validationError = validateDateRange(draft, bounds);
  const canApply = !validationError && !isLoading && !isSameRange(draft, appliedRange);

  const apply = (range) => {
    setDraft(range);
    if (!isSameRange(range, appliedRange)) onApply(range);
  };

  return (
    <>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (canApply) onApply(draft);
        }}
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

        <div className="flex flex-wrap items-center gap-2 lg:ml-auto" role="group" aria-label="Szybki wybór okresu">
          {quickRanges.map((range) => (
            <button
              key={range.label}
              type="button"
              onClick={() => apply(range)}
              disabled={isLoading}
              className={quickButtonClass(isSameRange(range, appliedRange))}
            >
              {range.label}
            </button>
          ))}
        </div>
      </form>
      {validationError && (
        <p role="alert" className="mt-2 text-sm text-red-600">
          {validationError}
        </p>
      )}
    </>
  );
}

export default PriceRangeForm;
