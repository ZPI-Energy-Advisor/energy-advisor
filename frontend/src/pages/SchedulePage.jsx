import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { FiCalendar, FiChevronLeft, FiChevronRight, FiShuffle } from "react-icons/fi";
import apiClient from "../api/client";
import DateRangePicker from "../components/DateRangePicker";
import ScheduleDayChart from "../components/ScheduleDayChart";
import SelectedFileBar from "../components/SelectedFileBar";
import { useEnergyFiles } from "../hooks/useEnergyFiles";
import { randomDay, rangeText, weekdayName } from "../utils/dateRange";
import { SOURCE_TYPE_DEVICES, getApiErrorMessage, isAggregateSource } from "../utils/energyFiles";
import { daySummaries, fixedDevices, flexibleActions } from "../utils/historicalSchedule";
import {
  afterRanges,
  clockRange,
  conflictText,
  dayOf,
  formatDayMonth,
  formatMoment,
  formatPln,
  isConflict,
  missingPricesNote,
  visibleDays,
} from "../utils/schedule";

const CARD = "bg-white p-4 md:p-5 rounded-lg shadow-sm border border-gray-100";
const PRESET_BUTTON =
  "inline-flex items-center gap-2 rounded-md border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50";
const NOTE = "p-3 text-sm text-amber-900 bg-amber-50 rounded-lg";

const dayOfAction = (isoTime) => formatDayMonth(isoTime.slice(0, 10));
const percent = (saved, before) => (before > 0 ? `${((saved / before) * 100).toFixed(1).replace(".", ",")}%` : undefined);
const kwhText = (value) => `${value.toFixed(1).replace(".", ",")} kWh`;

function StatTile({ label, value, hint, accent = false }) {
  return (
    <div className={CARD}>
      <p className="text-xs md:text-sm font-medium text-gray-500 mb-1">{label}</p>
      <div className={`text-lg md:text-2xl font-bold ${accent ? "text-emerald-700" : "text-gray-900"}`}>{value}</div>
      {hint && <p className="mt-1 text-xs text-gray-500">{hint}</p>}
    </div>
  );
}

function MovedTable({ actions }) {
  if (!actions.length) {
    return <p className="text-sm text-gray-500">Tego dnia żadne urządzenie nie zmieniło godzin: nie było taniej.</p>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="text-left text-gray-500 border-b border-gray-100">
          <tr>
            <th className="p-3 font-medium">Urządzenie</th>
            <th className="p-3 font-medium">Przed</th>
            <th className="p-3 font-medium">Po</th>
            <th className="p-3 font-medium text-right">Koszt przed</th>
            <th className="p-3 font-medium text-right">Koszt po</th>
          </tr>
        </thead>
        <tbody>
          {actions.map((action) => (
            <tr key={action.action_id} className="border-b border-gray-50 last:border-0">
              <td className="p-3">
                {action.device_name}
                {action.program_name && <span className="text-gray-500"> · {action.program_name}</span>}
              </td>
              <td className="p-3 whitespace-nowrap">{clockRange(action.original_start, action.original_end)}</td>
              <td className="p-3">{afterRanges(action)}</td>
              <td className="p-3 text-right whitespace-nowrap">{formatPln(action.cost_before)}</td>
              <td className="p-3 text-right whitespace-nowrap">{formatPln(action.cost_after)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// Wyniki dzień po dniu: jeden wykres naraz, strzałki i pasek dni z oszczędnością.
function DayBrowser({ days, index, onSelect, summaries, actions, prices, dateTo, browserRef }) {
  const day = days[index];
  const savings = Object.fromEntries(summaries.map((summary) => [summary.day, summary.saving]));
  const moved = actions.filter((action) => action.status === "moved" && dayOf(action.original_start) === day);

  return (
    <section ref={browserRef} className="space-y-4" aria-label="Wyniki dzień po dniu">
      {days.length > 1 && (
        <div className={`${CARD} space-y-3`}>
          <div className="flex items-center justify-between gap-3">
            <button
              type="button"
              className="p-2 rounded-md border border-gray-300 text-gray-700 hover:bg-gray-50 disabled:opacity-30"
              aria-label="Poprzedni dzień"
              disabled={index === 0}
              onClick={() => onSelect(index - 1)}
            >
              <FiChevronLeft aria-hidden="true" />
            </button>
            <div className="text-center">
              <p className="font-semibold text-gray-900">
                {formatDayMonth(day)}, {weekdayName(day)}
              </p>
              <p className="text-xs text-gray-500">Dzień {index + 1} z {days.length}</p>
            </div>
            <button
              type="button"
              className="p-2 rounded-md border border-gray-300 text-gray-700 hover:bg-gray-50 disabled:opacity-30"
              aria-label="Następny dzień"
              disabled={index === days.length - 1}
              onClick={() => onSelect(index + 1)}
            >
              <FiChevronRight aria-hidden="true" />
            </button>
          </div>
          <div className="flex gap-2 overflow-x-auto pb-1" role="tablist" aria-label="Dni okresu">
            {days.map((item, position) => (
              <button
                key={item}
                type="button"
                role="tab"
                aria-selected={position === index}
                className={`shrink-0 rounded-md border px-3 py-1.5 text-xs text-left ${
                  position === index
                    ? "border-emerald-600 bg-emerald-50 text-emerald-900"
                    : "border-gray-200 text-gray-700 hover:bg-gray-50"
                }`}
                onClick={() => onSelect(position)}
              >
                <span className="block font-semibold">{formatDayMonth(item)}</span>
                <span className="block text-gray-500">
                  {savings[item] != null ? formatPln(savings[item]) : "dokończenie"}
                </span>
              </button>
            ))}
          </div>
        </div>
      )}

      <ScheduleDayChart day={day} actions={actions} prices={prices} isTail={day > dateTo} />

      {day <= dateTo && (
        <div className={CARD}>
          <h3 className="font-semibold text-gray-900 mb-2">Przesunięte urządzenia</h3>
          <MovedTable actions={moved} />
        </div>
      )}
    </section>
  );
}

function DaySummaryTable({ summaries, onSelect }) {
  const total = summaries.reduce(
    (sum, item) => ({ moved: sum.moved + item.moved, before: sum.before + item.before, after: sum.after + item.after }),
    { moved: 0, before: 0, after: 0 },
  );
  return (
    <section className={CARD} aria-label="Podsumowanie okresu">
      <h3 className="font-semibold text-gray-900">Podsumowanie okresu</h3>
      <p className="text-xs text-gray-500 mb-3">
        Koszt urządzeń, które można przesuwać (bez urządzeń stałych i opłat stałych). Kliknij dzień, żeby zobaczyć wykres.
      </p>
      <div className="max-h-96 overflow-auto">
        <table className="w-full text-sm">
          <thead className="sticky top-0 bg-white text-left text-gray-500 border-b border-gray-100">
            <tr>
              <th className="p-2 font-medium">Dzień</th>
              <th className="p-2 font-medium text-right">Przesunięte</th>
              <th className="p-2 font-medium text-right">Koszt przed</th>
              <th className="p-2 font-medium text-right">Koszt po</th>
              <th className="p-2 font-medium text-right">Oszczędność</th>
            </tr>
          </thead>
          <tbody>
            {summaries.map((item, position) => (
              <tr
                key={item.day}
                className="border-b border-gray-50 cursor-pointer hover:bg-emerald-50"
                onClick={() => onSelect(position)}
              >
                <td className="p-2 whitespace-nowrap">
                  <button type="button" className="text-left hover:underline">
                    {formatDayMonth(item.day)}, {weekdayName(item.day)}
                  </button>
                </td>
                <td className="p-2 text-right">{item.moved}</td>
                <td className="p-2 text-right whitespace-nowrap">{formatPln(item.before)}</td>
                <td className="p-2 text-right whitespace-nowrap">{formatPln(item.after)}</td>
                <td className="p-2 text-right whitespace-nowrap font-medium text-emerald-700">{formatPln(item.saving)}</td>
              </tr>
            ))}
          </tbody>
          <tfoot className="sticky bottom-0 bg-white border-t border-gray-200 font-semibold text-gray-900">
            <tr>
              <td className="p-2">Razem</td>
              <td className="p-2 text-right">{total.moved}</td>
              <td className="p-2 text-right whitespace-nowrap">{formatPln(total.before)}</td>
              <td className="p-2 text-right whitespace-nowrap">{formatPln(total.after)}</td>
              <td className="p-2 text-right whitespace-nowrap text-emerald-700">{formatPln(total.before - total.after)}</td>
            </tr>
          </tfoot>
        </table>
      </div>
    </section>
  );
}

function FixedDevicesNote({ devices }) {
  if (!devices.length) return null;
  return (
    <details className="p-3 text-sm text-gray-700 bg-gray-50 rounded-lg">
      <summary className="cursor-pointer">
        Urządzenia stałe ({devices.length}) zostają o swoich godzinach, więc nie pokazujemy ich na wykresach.
      </summary>
      <ul className="mt-2 grid gap-x-6 gap-y-1 sm:grid-cols-2">
        {devices.map((device) => (
          <li key={device.deviceId} className="flex justify-between gap-3">
            <span>{device.name}</span>
            <span className="text-gray-500">{kwhText(device.energy)}</span>
          </li>
        ))}
      </ul>
      <p className="mt-2 text-xs text-gray-500">Liczą się w rachunku przed i po, tak samo w obu.</p>
    </details>
  );
}

// Optymalizacja historyczna: ile dałoby przesunięcie urządzeń z pliku na tańsze godziny w przeszłym okresie.
function SchedulePage() {
  const { selectedFile } = useEnergyFiles();
  // Zakres dotyczy pliku, dla którego został wybrany; nowy plik zaczyna od swojej pierwszej doby.
  const [range, setRange] = useState(null);
  const [schedule, setSchedule] = useState(null);
  const [error, setError] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [dayIndex, setDayIndex] = useState(0);
  const browserRef = useRef(null);
  const resultsRef = useRef(null);

  // Po policzeniu przewijamy do wyników, żeby było widać, że pojawiły się pod kalendarzem.
  useEffect(() => {
    if (schedule) resultsRef.current?.scrollIntoView?.({ behavior: "smooth", block: "start" });
  }, [schedule]);

  const fileRange = range?.fileId === selectedFile?.id ? range : null;
  const dateFrom = fileRange?.from ?? selectedFile?.data_start ?? "";
  const dateTo = fileRange?.to ?? selectedFile?.data_start ?? "";
  const shown = schedule?.fileId === selectedFile?.id ? schedule : null;
  const shownError = error?.fileId === selectedFile?.id ? error.message : null;
  // Optymalizacja przesuwa akcje urządzeń, więc ma sens tylko dla pojedynczego pliku urządzeń.
  const isDevicesFile =
    selectedFile && !isAggregateSource(selectedFile.id) && selectedFile.source_type === SOURCE_TYPE_DEVICES;

  const changeRange = (changes) => setRange({ fileId: selectedFile.id, from: dateFrom, to: dateTo, ...changes });

  const loadSchedule = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const { data } = await apiClient.get(`/energy-files/${selectedFile.id}/schedule`, {
        params: { from: dateFrom, to: dateTo },
      });
      setSchedule({ ...data, fileId: selectedFile.id });
      setDayIndex(0);
    } catch (loadError) {
      setSchedule(null);
      setError({
        message: getApiErrorMessage(loadError, "Nie udało się policzyć optymalizacji."),
        fileId: selectedFile.id,
      });
    } finally {
      setIsLoading(false);
    }
  };

  const selectDay = (index, scroll = false) => {
    setDayIndex(index);
    if (scroll) browserRef.current?.scrollIntoView?.({ behavior: "smooth", block: "start" });
  };

  // Pełny rachunek przed i po (jak w Wynikach kalkulacji); bez niego koszt samych akcji urządzeń.
  const hasBills = shown?.bill_before != null && shown?.bill_after != null;
  const before = shown ? (hasBills ? shown.bill_before : shown.cost_before) : 0;
  const after = shown ? (hasBills ? shown.bill_after : shown.cost_after) : 0;
  const saved = before - after;
  const flexible = shown ? flexibleActions(shown.actions) : [];
  const conflicts = flexible.filter(isConflict);
  const missingPrices = shown ? missingPricesNote(shown.missing_price_actions, shown.missing_price_days) : null;
  const days = shown ? visibleDays(shown.date_from, shown.date_to, flexible) : [];
  const summaries = shown ? daySummaries(shown.actions, shown.date_from, shown.date_to) : [];

  return (
    <div className="max-w-5xl mx-auto">
      <div className="border-b border-gray-200 pb-4 mb-6 md:mb-8">
        <h2 className="text-xl font-bold text-gray-900">Optymalizacja historyczna</h2>
        <p className="mt-1 text-sm text-gray-500">
          Sprawdź, ile zaoszczędziłbyś w wybranym okresie z przeszłości, gdyby pralka, zmywarka czy ładowanie auta
          pracowały w najtańszych godzinach. Bierzemy prawdziwe zużycie z pliku urządzeń i przesuwamy tylko to, co
          da się przesunąć, w dozwolonych godzinach. Reszta domu zostaje bez zmian.
        </p>
      </div>
      <SelectedFileBar />

      {!isDevicesFile ? (
        <p className="p-4 text-sm text-gray-600 bg-white rounded-lg border border-gray-100">
          Wybierz w imporcie danych pojedynczy plik urządzeń, aby zobaczyć optymalizację.
        </p>
      ) : (
        <div className="space-y-6">
          <section className={CARD} aria-label="Okres">
            <h3 className="font-semibold text-gray-900 mb-4">Wybierz okres</h3>
            <div className="flex flex-col gap-6 md:flex-row">
              <DateRangePicker
                key={selectedFile.id}
                min={selectedFile.data_start}
                max={selectedFile.data_end}
                from={dateFrom}
                to={dateTo}
                onChange={changeRange}
              />
              <div className="flex-1 space-y-4">
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    className={PRESET_BUTTON}
                    onClick={() => changeRange({ from: selectedFile.data_start, to: selectedFile.data_end })}
                  >
                    <FiCalendar aria-hidden="true" /> Cały okres pliku
                  </button>
                  <button
                    type="button"
                    className={PRESET_BUTTON}
                    onClick={() => {
                      const day = randomDay(selectedFile.data_start, selectedFile.data_end);
                      changeRange({ from: day, to: day });
                    }}
                  >
                    <FiShuffle aria-hidden="true" /> Losowy dzień
                  </button>
                </div>
                {dateFrom && dateTo && (
                  <p className="text-sm text-gray-700">
                    Wybrany okres: <span className="font-semibold">{rangeText(dateFrom, dateTo)}</span>
                  </p>
                )}
                <button
                  type="button"
                  onClick={loadSchedule}
                  disabled={isLoading || !dateFrom || !dateTo}
                  className="w-full sm:w-auto bg-emerald-600 text-white px-5 py-2.5 rounded-md font-semibold hover:bg-emerald-700 transition-colors disabled:opacity-50"
                >
                  {isLoading ? "Liczę..." : "Pokaż wynik"}
                </button>
              </div>
            </div>
          </section>

          {shownError && (
            <p className="p-3 text-sm text-red-600 bg-red-50 rounded-lg border border-red-200">{shownError}</p>
          )}

          {shown && (
            <>
              <div ref={resultsRef} className="grid grid-cols-1 sm:grid-cols-3 gap-3 scroll-mt-4">
                <StatTile label={hasBills ? "Rachunek przed" : "Koszt akcji przed"} value={formatPln(before)} />
                <StatTile label={hasBills ? "Rachunek po" : "Koszt akcji po"} value={formatPln(after)} />
                <StatTile label="Oszczędność" value={formatPln(saved)} hint={percent(saved, before)} accent />
              </div>

              <div className="text-xs text-gray-500 space-y-1">
                <p>
                  {hasBills
                    ? `Rachunek do zapłaty za ${rangeText(shown.date_from, shown.date_to)}${shown.bill_until ? ` z dokończeniem akcji do ${formatMoment(shown.bill_until)}` : ""}`
                    : `${shown.bill_note ?? ""} Koszt akcji urządzeń`}{" "}
                  przed i po przesunięciu urządzeń, według taryfy z profilu{shown.pricing ? `: ${shown.pricing}` : ""}.
                  {shown.max_grid_kw != null && (
                    <>
                      {" "}Limit poboru z sieci: {String(shown.max_grid_kw).replace(".", ",")} kW (moc umowna z{" "}
                      <Link to="/profile" className="underline">profilu</Link>).
                    </>
                  )}
                </p>
                <details>
                  <summary className="cursor-pointer text-gray-600 hover:text-gray-900">Jak liczymy?</summary>
                  <ul className="mt-2 list-disc pl-5 space-y-1">
                    <li>
                      {hasBills
                        ? "Rachunek liczymy jak w Wynikach kalkulacji: z opłatami stałymi, fotowoltaiką i depozytem."
                        : "Koszt akcji obejmuje energię, dystrybucję zmienną, opłaty za kWh i VAT, bez opłat stałych."}
                    </li>
                    {hasBills && shown.bill_until && (
                      <li>
                        Akcja zaczęta w okresie (np. nocne ładowanie auta) kończy się po jego końcu, więc rachunek obejmuje też
                        zużycie domu do {formatMoment(shown.bill_until)} i opłaty stałe za tę dobę, przed i po optymalizacji tak
                        samo. Dlatego może być wyższy niż w Wynikach kalkulacji za ten sam zakres.
                      </li>
                    )}
                    <li>Godziny dobieramy po cenach kwadransów; przy zwykłej taryfie bez PV zysk daje tylko przejście do tańszej strefy.</li>
                    <li>
                      Gdy panele oddają nadwyżkę do sieci, zużycie w tym kwadransie kosztuje wartość tej energii, więc urządzenia
                      chętnie trafiają na godziny produkcji.
                    </li>
                    <li>
                      Ładowanie auta rozkładamy na najtańsze kwadranse między podłączeniem a wyjazdem, także z przerwami
                      i po północy, jeśli auto stoi do rana.
                    </li>
                    <li>Wynik zakłada, że rano wiadomo, jakie urządzenia będą pracować danego dnia, więc pokazuje potencjał oszczędności.</li>
                  </ul>
                </details>
              </div>

              {missingPrices && <p className={NOTE}>{missingPrices}</p>}
              {shown.grid_limit_note && (
                <p className={NOTE}>
                  {shown.grid_limit_note}{" "}
                  <Link to="/profile" className="font-semibold underline">Przejdź do profilu</Link>
                </p>
              )}
              {shown.pv_note && (
                <p className={NOTE}>
                  {shown.pv_note}{" "}
                  <Link to="/profile" className="font-semibold underline">Przejdź do profilu</Link>
                </p>
              )}
              {conflicts.length > 0 && (
                <ul className={`${NOTE} space-y-1`}>
                  {conflicts.map((action) => (
                    <li key={action.action_id}>
                      <span className="font-medium">
                        {action.device_name} ({dayOfAction(action.original_start)} {clockRange(action.original_start, action.original_end)}):
                      </span>{" "}
                      {conflictText(action, shown.max_grid_kw)}
                    </li>
                  ))}
                </ul>
              )}

              <FixedDevicesNote devices={fixedDevices(shown.actions)} />

              <div className="flex flex-wrap gap-4 text-xs text-gray-600">
                <span className="flex items-center gap-1.5"><i className="w-4 h-2.5 rounded-sm bg-gray-300" /> przed</span>
                <span className="flex items-center gap-1.5"><i className="w-4 h-2.5 rounded-sm bg-emerald-500" /> po, przesunięte</span>
                <span className="flex items-center gap-1.5"><i className="w-4 h-2.5 rounded-sm bg-gray-400" /> po, bez zmian</span>
              </div>

              {days.length > 0 && (
                <DayBrowser
                  days={days}
                  index={Math.min(dayIndex, days.length - 1)}
                  onSelect={selectDay}
                  summaries={summaries}
                  actions={flexible}
                  prices={shown.prices}
                  dateTo={shown.date_to}
                  browserRef={browserRef}
                />
              )}

              {summaries.length > 1 && <DaySummaryTable summaries={summaries} onSelect={(index) => selectDay(index, true)} />}
            </>
          )}
        </div>
      )}
    </div>
  );
}

export default SchedulePage;
