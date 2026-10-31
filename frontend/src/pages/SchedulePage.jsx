import { useState } from "react";
import apiClient from "../api/client";
import ScheduleDayChart from "../components/ScheduleDayChart";
import SelectedFileBar from "../components/SelectedFileBar";
import { useEnergyFiles } from "../hooks/useEnergyFiles";
import { ALL_FILES_ID, getApiErrorMessage } from "../utils/energyFiles";
import { clockOf, describeReason, formatDayMonth, formatPln, visibleDays } from "../utils/schedule";

const shortTime = (isoTime) => `${formatDayMonth(isoTime.slice(0, 10))} ${clockOf(isoTime)}`;

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
  const isAggregate = selectedFile?.id === ALL_FILES_ID;

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
      setError(getApiErrorMessage(loadError, "Nie udało się policzyć optymalizacji."));
    } finally {
      setIsLoading(false);
    }
  };

  const saved = shown ? shown.cost_before - shown.cost_after : 0;
  const moved = shown ? shown.actions.filter((action) => action.status === "moved") : [];
  const conflicts = shown ? shown.actions.filter((action) => action.status === "conflict") : [];

  return (
    <div className="max-w-5xl mx-auto">
      <h2 className="text-xl font-bold text-gray-900 border-b border-gray-200 pb-4 mb-6 md:mb-8">Optymalizacja</h2>
      <SelectedFileBar />

      {!selectedFile || isAggregate ? (
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

          {error && <p className="p-3 text-sm text-red-600 bg-red-50 rounded-lg border border-red-200">{error}</p>}

          {shown && (
            <>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <StatTile label="Koszt przed" value={formatPln(shown.cost_before)} />
                <StatTile label="Koszt po" value={formatPln(shown.cost_after)} />
                <StatTile
                  label="Oszczędność"
                  value={formatPln(saved)}
                  hint={shown.cost_before > 0 ? `${((saved / shown.cost_before) * 100).toFixed(1)}%` : undefined}
                />
              </div>

              <p className="text-xs text-gray-500">
                Koszt energii przy cenach taryfy dynamicznej, bez opłat dystrybucyjnych. Wynik zakłada, że rano wiadomo,
                jakie akcje będą danego dnia, więc pokazuje potencjał oszczędności. Ładowanie EV nie jest jeszcze
                optymalizowane.
              </p>

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
                          <td className="p-3 whitespace-nowrap">{shortTime(action.original_start)}</td>
                          <td className="p-3 whitespace-nowrap">{shortTime(action.start)}</td>
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
                      <span className="font-medium">{action.device_name} ({shortTime(action.original_start)}):</span>{" "}
                      {describeReason(action.reason)}
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
