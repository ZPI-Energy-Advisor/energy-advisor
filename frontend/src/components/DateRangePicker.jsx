import { useState } from "react";
import { FiChevronLeft, FiChevronRight } from "react-icons/fi";
import { WEEKDAY_SHORT, addMonths, monthOf, monthTitle, monthWeeks } from "../utils/dateRange";

// Kalendarz miesiąca do wyboru zakresu dni w granicach pliku: pierwsze kliknięcie wybiera jeden dzień,
// drugie kończy zakres (w dowolnej kolejności). Dni spoza pliku są wyłączone.
// `showEnd`: kalendarz pokazuje miesiąc końca zakresu zamiast początku (ceny: liczą się ostatnie dni).
function DateRangePicker({ min, max, from, to, onChange, showEnd = false }) {
  const focusOf = (range) => (showEnd ? range.to : range.from);
  const [month, setMonth] = useState(monthOf(focusOf({ from, to }) || (showEnd ? max : min)));
  const [anchor, setAnchor] = useState(null);
  const [shown, setShown] = useState({ from, to });
  // Okres zmieniony z zewnątrz (cały okres, losowy dzień, szybki wybór): kalendarz pokazuje jego miesiąc,
  // a rozpoczęte kliknięciem zaznaczanie się kończy.
  if (from !== shown.from || to !== shown.to) {
    const focus = focusOf({ from, to });
    if (focus && focus !== focusOf(shown) && monthOf(focus) !== month) setMonth(monthOf(focus));
    if (anchor !== null && (from !== anchor || to !== anchor)) setAnchor(null);
    setShown({ from, to });
  }
  const canGoBack = month > monthOf(min);
  const canGoForward = month < monthOf(max);

  const pick = (day) => {
    if (anchor === null) {
      onChange({ from: day, to: day });
      setAnchor(day);
      return;
    }
    onChange(anchor <= day ? { from: anchor, to: day } : { from: day, to: anchor });
    setAnchor(null);
  };

  const dayClass = (day) => {
    const selected = from && to && day >= from && day <= to;
    const edge = day === from || day === to;
    if (edge) return "bg-emerald-600 text-white font-semibold";
    if (selected) return "bg-emerald-100 text-emerald-900";
    return "text-gray-800 hover:bg-gray-100";
  };

  return (
    <div className="w-full max-w-xs">
      <div className="flex items-center justify-between mb-2">
        <button
          type="button"
          className="p-1.5 rounded text-gray-600 hover:bg-gray-100 disabled:opacity-30"
          aria-label="Poprzedni miesiąc"
          disabled={!canGoBack}
          onClick={() => setMonth(addMonths(month, -1))}
        >
          <FiChevronLeft aria-hidden="true" />
        </button>
        <p className="text-sm font-semibold text-gray-900 capitalize">{monthTitle(month)}</p>
        <button
          type="button"
          className="p-1.5 rounded text-gray-600 hover:bg-gray-100 disabled:opacity-30"
          aria-label="Następny miesiąc"
          disabled={!canGoForward}
          onClick={() => setMonth(addMonths(month, 1))}
        >
          <FiChevronRight aria-hidden="true" />
        </button>
      </div>
      <table className="w-full text-center text-sm" role="grid" aria-label={monthTitle(month)}>
        <thead>
          <tr>
            {WEEKDAY_SHORT.map((day) => (
              <th key={day} className="pb-1 text-xs font-medium text-gray-400">{day}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {monthWeeks(month).map((week, index) => (
            <tr key={index}>
              {week.map((day, position) => (
                <td key={day ?? `empty-${position}`} className="p-0.5">
                  {day && (
                    <button
                      type="button"
                      className={`w-9 h-9 rounded-md transition-colors disabled:text-gray-300 disabled:hover:bg-transparent ${dayClass(day)}`}
                      disabled={day < min || day > max}
                      aria-pressed={Boolean(from && to && day >= from && day <= to)}
                      aria-label={day}
                      onClick={() => pick(day)}
                    >
                      {Number(day.slice(8, 10))}
                    </button>
                  )}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 text-xs text-gray-500">
        {anchor ? "Kliknij ostatni dzień okresu albo ten sam dzień jeszcze raz." : "Kliknij pierwszy dzień, a potem ostatni."}
      </p>
    </div>
  );
}

export default DateRangePicker;
