import { useMemo, useState } from "react";
import DateRangePicker from "./DateRangePicker";
import { countDays, formatDate, isSameRange, validateDateRange } from "../utils/energyFiles";
import { buildPriceQuickRanges, formatDaysCount } from "../utils/dynamicPrices";
import { buttonClass } from "./uiStyles";

const quickButtonClass = (isActive) =>
  `px-3 py-2 text-xs md:text-sm font-medium rounded-lg border transition-colors whitespace-nowrap disabled:opacity-60 ${
    isActive
      ? "bg-emerald-50 border-emerald-500 text-emerald-700"
      : "bg-white border-gray-200 text-gray-600 hover:border-emerald-300 hover:text-emerald-700"
  }`;

// Okres cen jak w optymalizacji historycznej: zakres klikany w kalendarzu (pierwszy i ostatni dzień) albo
// szybkim wyborem (7/30/90 dni, rok, cały okres) tylko zaznacza okres; wykres zmienia się po „Pokaż ceny”.
function PriceRangeForm({ bounds, appliedRange, onApply, isLoading }) {
  const [draft, setDraft] = useState(appliedRange);
  const quickRanges = useMemo(() => buildPriceQuickRanges(bounds), [bounds]);

  const validationError = validateDateRange(draft, bounds);
  const changed = !isSameRange(draft, appliedRange);


  return (
    <div className="flex flex-col gap-6 md:flex-row">
      <DateRangePicker min={bounds.from} max={bounds.to} from={draft.from} to={draft.to} onChange={setDraft} showEnd />
      <div className="flex-1 space-y-4">
        <div className="flex flex-wrap gap-2" role="group" aria-label="Szybki wybór okresu">
          {quickRanges.map((range) => (
            <button
              key={range.label}
              type="button"
              onClick={() => setDraft(range)}
              aria-pressed={isSameRange(range, draft)}
              className={quickButtonClass(isSameRange(range, draft))}
            >
              {range.label}
            </button>
          ))}
        </div>
        <p className="text-sm text-gray-700">
          Wybrany okres:{" "}
          <span className="font-semibold">
            {formatDate(draft.from)} – {formatDate(draft.to)}
          </span>{" "}
          ({formatDaysCount(countDays(draft))})
        </p>
        {validationError && (
          <p role="alert" className="text-sm text-red-600">
            {validationError}
          </p>
        )}
        <button
          type="button"
          onClick={() => onApply(draft)}
          disabled={!changed || Boolean(validationError) || isLoading}
          className={`${buttonClass("primary", "lg")} w-full sm:w-auto`}
        >
          {isLoading ? "Ładowanie..." : "Pokaż ceny"}
        </button>
      </div>
    </div>
  );
}

export default PriceRangeForm;
