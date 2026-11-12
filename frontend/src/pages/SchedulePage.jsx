import { useState } from "react";
import apiClient from "../api/client";
import { Link } from "react-router-dom";
import ScheduleDayChart from "../components/ScheduleDayChart";
import SelectedFileBar from "../components/SelectedFileBar";
import { useEnergyFiles } from "../hooks/useEnergyFiles";
import { SOURCE_TYPE_DEVICES, getApiErrorMessage, isAggregateSource } from "../utils/energyFiles";
import {
  afterRanges,
  clockRange,
  conflictText,
  formatDayMonth,
  formatMoment,
  formatPln,
  isConflict,
  missingPricesNote,
  visibleDays,
} from "../utils/schedule";

const dayOfAction = (isoTime) => formatDayMonth(isoTime.slice(0, 10));

function StatTile({ label, value, hint }) {
  return (
    <div className="bg-white p-4 md:p-5 rounded-lg shadow-sm border border-gray-100">
      <p className="text-xs md:text-sm font-medium text-gray-500 mb-1">{label}</p>
      <div className="text-lg md:text-2xl font-bold text-gray-900">{value}</div>
      {hint && <p className="mt-1 text-xs text-gray-500">{hint}</p>}
    </div>
  );
}

function SchedulePage() {
  const { selectedFile } = useEnergyFiles();
  // Zakres dotyczy pliku, dla którego został wybrany; nowy plik zaczyna od swojej pierwszej doby.
  const [range, setRange] = useState(null);
  const [schedule, setSchedule] = useState(null);
  const [error, setError] = useState(null);
  const [isLoading, setIsLoading] = useState(false);

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

  // Pełny rachunek przed i po (jak w Wynikach kalkulacji); bez niego koszt samych akcji urządzeń.
  const hasBills = shown?.bill_before != null && shown?.bill_after != null;
  const before = shown ? (hasBills ? shown.bill_before : shown.cost_before) : 0;
  const after = shown ? (hasBills ? shown.bill_after : shown.cost_after) : 0;
  const saved = before - after;
  const moved = shown ? shown.actions.filter((action) => action.status === "moved") : [];
  const conflicts = shown ? shown.actions.filter(isConflict) : [];
  const missingPrices = shown ? missingPricesNote(shown.missing_price_actions, shown.missing_price_days) : null;

  return (
    <div className="max-w-5xl mx-auto">
      <h2 className="text-xl font-bold text-gray-900 border-b border-gray-200 pb-4 mb-6 md:mb-8">Optymalizacja</h2>
      <SelectedFileBar />

      {!isDevicesFile ? (
        <p className="p-4 text-sm text-gray-600 bg-white rounded-lg border border-gray-100">
          Wybierz w imporcie danych pojedynczy plik urządzeń, aby zobaczyć optymalizację.
        </p>
      ) : (
        <div className="space-y-6">
          <div className="flex flex-wrap items-end gap-3 bg-white p-4 rounded-lg shadow-sm border border-gray-100">
            <label className="text-sm text-gray-600">
              Od
              <input
                type="date"
                value={dateFrom}
                min={selectedFile.data_start}
                max={selectedFile.data_end}
                onChange={(event) => changeRange({ from: event.target.value })}
                className="block mt-1 border border-gray-300 rounded px-2 py-1.5 text-gray-900"
              />
            </label>
            <label className="text-sm text-gray-600">
              Do
              <input
                type="date"
                value={dateTo}
                min={dateFrom}
                max={selectedFile.data_end}
                onChange={(event) => changeRange({ to: event.target.value })}
                className="block mt-1 border border-gray-300 rounded px-2 py-1.5 text-gray-900"
              />
            </label>
            <button
              type="button"
              onClick={loadSchedule}
              disabled={isLoading || !dateFrom || !dateTo}
              className="bg-emerald-600 text-white px-5 py-2 rounded font-medium hover:bg-emerald-700 transition-colors disabled:opacity-50"
            >
              {isLoading ? "Liczę..." : "Pokaż"}
            </button>
          </div>

          {shownError && (
            <p className="p-3 text-sm text-red-600 bg-red-50 rounded-lg border border-red-200">{shownError}</p>
          )}

          {shown && (
            <>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <StatTile label={hasBills ? "Rachunek przed" : "Koszt akcji przed"} value={formatPln(before)} />
                <StatTile label={hasBills ? "Rachunek po" : "Koszt akcji po"} value={formatPln(after)} />
                <StatTile
                  label="Oszczędność"
                  value={formatPln(saved)}
                  hint={before > 0 ? `${((saved / before) * 100).toFixed(1)}%` : undefined}
                />
              </div>

              <div className="text-xs text-gray-500 space-y-1">
                <p>
                  {hasBills
                    ? `Rachunek do zapłaty za wybrany okres${shown.bill_until ? ` z dokończeniem akcji do ${formatMoment(shown.bill_until)}` : ""}`
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
                      Gdy panele oddają nadwyżkę do sieci, zużycie w tym kwadransie kosztuje wartość tej energii (w net-billingu RCE
                      albo RCEm z profilu, od 02.2025 × 1,23), więc urządzenia chętnie trafiają na godziny produkcji.
                    </li>
                    <li>
                      Ładowanie EV rozkładamy na najtańsze kwadranse między podłączeniem auta a wyjazdem, także z przerwami
                      i po północy, jeśli auto stoi do rana.
                    </li>
                    <li>Limit poboru z sieci liczymy jak licznik: zużycie pracujących urządzeń minus bieżąca produkcja PV.</li>
                    <li>Wynik zakłada, że rano wiadomo, jakie akcje będą danego dnia, więc pokazuje potencjał oszczędności.</li>
                  </ul>
                </details>
              </div>

              {missingPrices && (
                <p className="p-3 text-sm text-amber-900 bg-amber-50 rounded-lg">{missingPrices}</p>
              )}
              {shown.grid_limit_note && (
                <p className="p-3 text-sm text-amber-900 bg-amber-50 rounded-lg">
                  {shown.grid_limit_note}{" "}
                  <Link to="/profile" className="font-semibold underline">Przejdź do profilu</Link>
                </p>
              )}
              {shown.pv_note && (
                <p className="p-3 text-sm text-amber-900 bg-amber-50 rounded-lg">
                  {shown.pv_note}{" "}
                  <Link to="/profile" className="font-semibold underline">Przejdź do profilu</Link>
                </p>
              )}

              <div className="flex flex-wrap gap-4 text-xs text-gray-600">
                <span className="flex items-center gap-1.5"><i className="w-4 h-2.5 rounded-sm bg-gray-300" /> przed</span>
                <span className="flex items-center gap-1.5"><i className="w-4 h-2.5 rounded-sm bg-emerald-500" /> po, przesunięte</span>
                <span className="flex items-center gap-1.5"><i className="w-4 h-2.5 rounded-sm bg-gray-400" /> po, bez zmian</span>
              </div>

              {visibleDays(shown.date_from, shown.date_to, shown.actions).map((day) => (
                <ScheduleDayChart
                  key={day}
                  day={day}
                  actions={shown.actions}
                  prices={shown.prices}
                  isTail={day > shown.date_to}
                />
              ))}

              {moved.length > 0 && (
                <section className="bg-white rounded-lg shadow-sm border border-gray-100 overflow-x-auto">
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
                      {moved.map((action) => (
                        <tr key={action.action_id} className="border-b border-gray-50 last:border-0">
                          <td className="p-3">
                            {action.device_name}
                            {action.program_name && <span className="text-gray-500"> · {action.program_name}</span>}
                          </td>
                          <td className="p-3 whitespace-nowrap">
                            {dayOfAction(action.original_start)} {clockRange(action.original_start, action.original_end)}
                          </td>
                          <td className="p-3">{afterRanges(action, { withDay: true })}</td>
                          <td className="p-3 text-right whitespace-nowrap">{formatPln(action.cost_before)}</td>
                          <td className="p-3 text-right whitespace-nowrap">{formatPln(action.cost_after)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </section>
              )}

              {conflicts.length > 0 && (
                <ul className="p-3 text-sm text-amber-900 bg-amber-50 rounded-lg space-y-1">
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
            </>
          )}
        </div>
      )}
    </div>
  );
}

export default SchedulePage;
