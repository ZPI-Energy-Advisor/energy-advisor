import { formatDate } from "../utils/energyFiles";
import { formatDayGroup, formatDaysCount, groupConsecutiveDays } from "../utils/dynamicPrices";

const MAX_LISTED_GROUPS = 6;

function DayGroups({ title, days, className }) {
  if (days.length === 0) return null;
  const groups = groupConsecutiveDays(days);
  const shown = groups.slice(0, MAX_LISTED_GROUPS);

  return (
    <div className="flex flex-wrap items-center gap-1.5 text-xs">
      <span className="font-medium text-gray-600">{title}:</span>
      {shown.map((group) => (
        <span key={group.from} className={`px-2 py-0.5 rounded-full border ${className}`}>
          {formatDayGroup(group)}
        </span>
      ))}
      {groups.length > shown.length && (
        <span className="text-gray-500">i {groups.length - shown.length} więcej okresów</span>
      )}
    </div>
  );
}

function PriceDataCompleteness({ days, showsHourlyPricesNote }) {
  return (
    <div className="mt-4 md:mt-6 space-y-2 border-t border-gray-100 pt-4">
      <p className="text-xs md:text-sm text-gray-600">
        Kompletność danych:{" "}
        <span className="font-semibold text-gray-800">
          {days.complete} z {formatDaysCount(days.total)} pełnych
        </span>
        {days.incomplete.length === 0 && days.missing.length === 0 && " - brak luk w danych."}
      </p>
      <DayGroups title="Brak danych" days={days.missing} className="bg-slate-100 border-slate-200 text-slate-600" />
      <DayGroups title="Niepełne dane" days={days.incomplete} className="bg-amber-50 border-amber-200 text-amber-800" />
      {showsHourlyPricesNote && (
        <p className="text-xs text-gray-500">
          Do {formatDate("2025-09-30")} PSE publikowało ceny godzinowe - w tym okresie kwadranse w ramach godziny mają tę samą cenę.
        </p>
      )}
    </div>
  );
}

export default PriceDataCompleteness;
