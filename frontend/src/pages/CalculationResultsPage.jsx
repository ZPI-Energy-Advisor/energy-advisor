import { useCallback, useEffect, useState } from "react";
import { FiAlertCircle, FiRefreshCw } from "react-icons/fi";
import apiClient from "../api/client";
import SelectedFileBar from "../components/SelectedFileBar";
import NoFileData from "../components/NoFileData";
import { getApiErrorMessage, isAggregateSource } from "../utils/energyFiles";
import { useEnergyFiles } from "../hooks/useEnergyFiles";

const formatMoney = (value) =>
  value == null
    ? "—"
    : `${Number(value).toLocaleString("pl-PL", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      })} PLN`;

const formatDate = (value) =>
  value == null ? "—" : new Date(value).toLocaleDateString("pl-PL");

const formatPeriod = (cycle) =>
  `${formatDate(cycle.cycle_start)} – ${formatDate(cycle.cycle_end)}`;

const formatKwh = (value) =>
  `${Number(value).toLocaleString("pl-PL", { maximumFractionDigits: 0 })} kWh`;

// Składniki rachunku netto w okresie, w kolejności z faktury.
const CYCLE_COLUMNS = [
  ["active_energy_net", "Energia czynna"],
  ["excise_net", "Akcyza"],
  ["variable_network_net", "Dystrybucja zmienna"],
  ["quality_net", "Opłata jakościowa"],
  ["renewable_net", "Opłata OZE"],
  ["cogeneration_net", "Opłata kogeneracyjna"],
  ["fixed_network_net", "Opłata stała"],
  ["subscription_net", "Abonament"],
  ["capacity_net", "Opłata mocowa"],
  ["transition_net", "Opłata przejściowa"],
  ["trade_fee_net", "Opłata handlowa"],
  ["vat", "VAT"],
];

const OPERATOR_NAMES = {
  PGE: "PGE Dystrybucja",
  TAURON: "TAURON Dystrybucja",
  ENEA: "Enea Operator",
  ENERGA: "Energa-Operator",
  STOEN: "Stoen Operator",
};

const modeLabels = {
  net_metering: "Net-metering",
  net_billing: "Net-billing",
};

// Kwota do zapłaty w porównaniu taryf; przy depozycie prosumenta pod spodem brutto i depozyt.
function PriceCell({ result, selected }) {
  if (!result) {
    return <td className="whitespace-nowrap px-5 py-4 text-right text-sm text-gray-400">—</td>;
  }
  return (
    <td className={`whitespace-nowrap px-5 py-4 text-right text-sm ${selected ? "bg-emerald-50" : ""}`}>
      {selected && (
        <span className="mr-2 rounded-full bg-blue-100 px-2 py-1 text-xs font-medium text-blue-800">Z profilu</span>
      )}
      <span className="font-bold text-emerald-700">{formatMoney(result.payable_gross)}</span>
      {Number(result.deposit_amount) > 0 && (
        <p className="text-xs text-gray-500">
          brutto {formatMoney(result.gross_total)}, depozyt {formatMoney(result.deposit_amount)}
        </p>
      )}
    </td>
  );
}

function Metric({ label, value, accent = false }) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-4">
      <p className="text-xs font-medium uppercase tracking-wide text-gray-500">{label}</p>
      <p className={`mt-2 text-xl font-bold ${accent ? "text-emerald-700" : "text-gray-900"}`}>
        {value}
      </p>
    </div>
  );
}

function CalculationResultsPage() {
  const { isReady, selectedFile, selectedFileId } = useEnergyFiles();
  const [calculation, setCalculation] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);

  const loadCalculation = useCallback(async () => {
    if (!selectedFileId || isAggregateSource(selectedFileId)) {
      setCalculation(null);
      return;
    }

    setIsLoading(true);
    setError(null);
    try {
      const { data } = await apiClient.get(
        `/upload/calculation-details/${selectedFileId}`,
      );
      setCalculation(data);
    } catch (requestError) {
      setCalculation(null);
      setError(
        getApiErrorMessage(
          requestError,
          "Nie udało się pobrać wyników kalkulacji.",
        ),
      );
    } finally {
      setIsLoading(false);
    }
  }, [selectedFileId]);

  useEffect(() => {
    if (isReady) {
      Promise.resolve().then(loadCalculation);
    }
  }, [isReady, loadCalculation]);

  if (!isReady) {
    return <div className="p-10 text-gray-500">Ładowanie danych kalkulacji...</div>;
  }

  if (!selectedFile || isAggregateSource(selectedFileId)) {
    return (
      <div className="max-w-6xl mx-auto">
        <h2 className="text-xl font-bold text-gray-900 border-b border-gray-200 pb-4 mb-8">
          Wyniki kalkulacji
        </h2>
        <NoFileData
          emptyTitle="Wybierz pojedynczy plik"
          emptyDescription="Wyniki silnika taryfowego są dostępne dla konkretnego pliku z odczytami."
        />
      </div>
    );
  }

  const tariffCalculation = calculation?.tariff_calculation;
  const tariffCalculations = calculation?.tariff_calculations ?? {};
  const dynamicCalculations = calculation?.dynamic_calculations ?? {};
  // Wiersz = grupa taryfowa; obok zwykłej umowy ta sama grupa z ceną dynamiczną (jeśli sprzedawca ją dopuszcza).
  const tariffRows = [
    ...Object.keys(tariffCalculations),
    ...Object.keys(dynamicCalculations).filter((group) => !(group in tariffCalculations)),
  ].map((group) => [group, tariffCalculations[group], dynamicCalculations[group]]);
  const hasDynamic = Object.keys(dynamicCalculations).length > 0;
  const dynamicName = Object.values(dynamicCalculations)[0]?.name ?? "Cena dynamiczna";
  const selectedDynamic = Boolean(calculation?.tariff_data?.dynamic_price);
  const tariffCalculationErrors = calculation?.tariff_calculation_errors ?? {};
  const selectedTariff = calculation?.tariff_data?.tariff_type;
  const cycles = tariffCalculation?.cycles ?? [];
  const pvMode = calculation?.pv_details?.mode;
  const annualConsumption = calculation?.annual_consumption;
  const unsupportedTariffs = calculation?.unsupported_tariffs ?? [];
  const tariffNotes = Object.values(calculation?.tariff_notes ?? {});
  const operatorCode = calculation?.tariff_data?.distribution_operator;
  const operatorName = OPERATOR_NAMES[operatorCode] ?? operatorCode;
  const selectedHasTradeFee = Number(tariffCalculation?.trade_fee_net) > 0;
  const cycleColumns = CYCLE_COLUMNS.filter(
    ([key]) => key !== "trade_fee_net" || selectedHasTradeFee,
  );

  return (
    <div className="mx-auto max-w-6xl pb-12">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3 border-b border-gray-200 pb-4">
        <div>
          <h2 className="text-xl font-bold text-gray-900">Wyniki kalkulacji</h2>
          <p className="mt-1 text-sm text-gray-500">
            PV Balancer → silnik taryfowy → rozliczenie finansowe
          </p>
        </div>
        <button
          type="button"
          onClick={loadCalculation}
          disabled={isLoading}
          className="inline-flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-60"
        >
          <FiRefreshCw className={isLoading ? "animate-spin" : ""} />
          Odśwież
        </button>
      </div>

      <SelectedFileBar />

      {error && (
        <div className="mb-6 flex items-start gap-3 rounded-lg bg-red-50 p-4 text-sm text-red-700">
          <FiAlertCircle className="mt-0.5 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {isLoading && !calculation && (
        <div className="rounded-xl border border-gray-200 bg-white p-8 text-center text-gray-500">
          Pobieranie wyników kalkulacji...
        </div>
      )}

      {!isLoading && calculation && tariffRows.length === 0 && !tariffCalculation && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-5 text-sm text-amber-800">
          Endpoint zwrócił dane wejściowe, ale nie zawiera jeszcze wyniku finansowego.
        </div>
      )}

      {calculation?.warnings?.map((warning) => (
        <div key={warning} className="mb-6 flex items-start gap-3 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
          <FiAlertCircle className="mt-0.5 shrink-0" />
          <span>{warning}</span>
        </div>
      ))}

      {tariffRows.length > 0 && (
        <div className="mb-6 overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm">
          <div className="border-b border-gray-200 px-5 py-4">
            <h3 className="font-semibold text-gray-900">Porównanie taryf</h3>
            <p className="mt-1 text-sm text-gray-500">
              Ten sam plik i profil PV policzone dla każdej grupy taryfowej operatora: przy zwykłej umowie
              {hasDynamic && ` i z ceną dynamiczną (${dynamicName}; dystrybucja według grupy, okres rozliczeniowy oferty)`}.
              Kwoty do zapłaty brutto.
            </p>
          </div>
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  {["Grupa taryfowa", "Zwykła umowa", ...(hasDynamic ? ["Cena dynamiczna"] : [])].map((label) => (
                    <th key={label} className="whitespace-nowrap px-5 py-3 text-right text-xs font-medium uppercase tracking-wide text-gray-500 first:text-left">
                      {label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {tariffRows.map(([group, regular, dynamic]) => (
                  <tr key={group} className="hover:bg-gray-50">
                    <td className="whitespace-nowrap px-5 py-4 text-sm font-semibold text-gray-900">{group}</td>
                    <PriceCell result={regular} selected={group === selectedTariff && !selectedDynamic} />
                    {hasDynamic && <PriceCell result={dynamic} selected={group === selectedTariff && selectedDynamic} />}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {unsupportedTariffs.length > 0 && (
            <p className="border-t border-gray-100 px-5 py-3 text-xs text-gray-500">
              U operatora {operatorName} są też:{" "}
              {unsupportedTariffs.map((item, index) => (
                <span key={item.code}>
                  {index > 0 && ", "}
                  <span title={item.reason} className="cursor-help underline decoration-dotted">{item.code}</span>
                </span>
              ))}
              . Jeszcze ich nie liczymy.
            </p>
          )}
          {tariffNotes.map((note) => (
            <p key={note} className="border-t border-gray-100 px-5 py-2 text-xs text-gray-500">{note}</p>
          ))}
        </div>
      )}

      {Object.keys(tariffCalculationErrors).length > 0 && (
        <div className="mb-6 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
          Nie pokazano taryf bez kompletu danych:{" "}
          {Object.keys(tariffCalculationErrors).join(", ")}.
        </div>
      )}

      {tariffCalculation && (
        <>
          <div className="mb-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Metric label="Rachunek brutto" value={formatMoney(tariffCalculation.gross_total)} />
            <Metric label="Do zapłaty" value={formatMoney(tariffCalculation.payable_gross)} accent />
            <Metric label="Depozyt" value={formatMoney(tariffCalculation.deposit_amount)} />
            <Metric label="Potrącono z energii czynnej" value={formatMoney(tariffCalculation.deposit_applied)} />
          </div>

          <div className="mb-6 rounded-xl border border-gray-200 bg-white p-5">
            <div className="grid gap-4 text-sm sm:grid-cols-2 lg:grid-cols-4">
              <div>
                <span className="text-gray-500">Tryb PV</span>
                <p className="mt-1 font-semibold text-gray-900">
                  {pvMode ? modeLabels[pvMode] ?? pvMode : "Brak instalacji PV"}
                </p>
              </div>
              <div>
                <span className="text-gray-500">Energia czynna brutto</span>
                <p className="mt-1 font-semibold text-gray-900">
                  {formatMoney(tariffCalculation.active_energy_gross)}
                </p>
              </div>
              <div>
                <span className="text-gray-500">Liczba okresów</span>
                <p className="mt-1 font-semibold text-gray-900">{cycles.length}</p>
              </div>
              {annualConsumption && (
                <div>
                  <span className="text-gray-500">Roczne zużycie (próg opłaty mocowej)</span>
                  <p className="mt-1 font-semibold text-gray-900">{formatKwh(annualConsumption.annual_kwh)}</p>
                  {annualConsumption.scaled && (
                    <p className="mt-0.5 text-xs text-gray-500">
                      przeskalowane z {annualConsumption.days} dni pliku
                    </p>
                  )}
                </div>
              )}
            </div>
          </div>

          <div className="overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm">
            <div className="border-b border-gray-200 px-5 py-4">
              <h3 className="font-semibold text-gray-900">Rozliczenie okresów</h3>
            </div>
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-50">
                  <tr>
                    {["Okres", ...cycleColumns.map(([, label]) => label), "Brutto"].map((label) => (
                      <th key={label} className="whitespace-nowrap px-5 py-3 text-right text-xs font-medium uppercase tracking-wide text-gray-500 first:text-left">
                        {label}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {cycles.map((cycle) => (
                    <tr key={cycle.cycle_start} className="hover:bg-gray-50">
                      <td className="whitespace-nowrap px-5 py-4 text-sm font-medium text-gray-900">
                        {formatPeriod(cycle)}
                        {cycle.days_billed < cycle.days_in_cycle && (
                          <p className="text-xs font-normal text-gray-500">
                            opłaty miesięczne za {cycle.days_billed} z {cycle.days_in_cycle} dni (okres pliku)
                          </p>
                        )}
                      </td>
                      {cycleColumns.map(([key]) => (
                        <td key={key} className="whitespace-nowrap px-5 py-4 text-right text-sm">
                          {formatMoney(cycle[key])}
                        </td>
                      ))}
                      <td className="whitespace-nowrap px-5 py-4 text-right text-sm font-semibold">{formatMoney(cycle.gross_total)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

export default CalculationResultsPage;
