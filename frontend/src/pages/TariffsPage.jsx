import { useEffect, useState } from "react";
import { FiAlertCircle } from "react-icons/fi";
import DataContextBar from "../components/DataContextBar";
import { PageSkeleton } from "../components/Skeleton";
import NoFileData from "../components/NoFileData";
import NoDataInRange from "../components/NoDataInRange";
import ProfileTariffNotice from "../components/ProfileTariffNotice";
import TariffSummaryCards from "../components/tariffs/TariffSummaryCards";
import TariffMatrix from "../components/tariffs/TariffMatrix";
import TariffDayChart from "../components/tariffs/TariffDayChart";
import TariffBillDetails from "../components/tariffs/TariffBillDetails";
import { useEnergyFiles } from "../hooks/useEnergyFiles";
import { useTariffComparison } from "../hooks/useTariffComparison";
import { hasDataInRange } from "../utils/energyFiles";
import { OPERATOR_NAMES, detailsKey, findEntry } from "../utils/tariffComparison";

function Warning({ children }) {
  return (
    <div className="mb-4 flex items-start gap-3 rounded-lg border border-amber-200 bg-amber-50 p-3 md:p-4 text-sm text-amber-800">
      <FiAlertCircle className="mt-0.5 shrink-0" />
      <span>{children}</span>
    </div>
  );
}

function TariffsPage() {
  const {
    isReady, results, isLoadingData, selectedFile, viewSource, cacheScope, comparisonCache, requireAllTariffs,
    dataError, reloadData,
  } = useEnergyFiles();
  // Porównanie startuje razem z /data (także przy pierwszym wejściu); nie pytamy tylko o zakres, o którym już wiemy,
  // że nie ma pomiarów.
  const emptyRange = Boolean(selectedFile) && !isLoadingData && !hasDataInRange(results);
  const { comparison, isLoading, error, retry } = useTariffComparison(
    emptyRange ? null : viewSource, cacheScope, comparisonCache,
  );
  const [chosenKey, setChosenKey] = useState(null);

  useEffect(() => {
    requireAllTariffs(true);
    return () => requireAllTariffs(false);
  }, [requireAllTariffs]);

  if (!isReady) {
    return <PageSkeleton label="Ładowanie analizy taryf..." />;
  }

  const operator = comparison?.operator ?? results?.pricing?.operator;
  const shownKey = detailsKey(comparison, chosenKey);
  const shownEntry = findEntry(comparison, shownKey);
  const busy = isLoading || isLoadingData;

  return (
    <div className="mx-auto max-w-6xl pb-12">
      <DataContextBar
        title="Analiza taryf"
        subtitle={
          operator && (
            <>
              Taryfy operatora {OPERATOR_NAMES[operator] ?? operator}
              {comparison?.from_profile ? " z Twojego profilu" : ""}: rachunek do zapłaty brutto z opłatami
              miesięcznymi, a przy PV z depozytem prosumenta.
            </>
          )
        }
      />

      <ProfileTariffNotice
        missingProfile=", żebyśmy mogli oznaczyć Twoją taryfę i policzyć rachunek z Twoim okresem rozliczeniowym i PV. Do tego czasu porównujemy taryfy operatora PGE."
        pricingNote={comparison?.selection_note}
      />


      {!selectedFile ? (
        <NoFileData
          emptyTitle="Brak danych do porównania"
          emptyDescription="Wgraj plik z odczytami licznika albo urządzeń, aby porównać taryfy."
        />
      ) : !hasDataInRange(results) ? (
        <NoDataInRange />
      ) : (
        <div className={`transition-opacity ${busy ? "opacity-60" : ""}`} aria-busy={busy}>
          {comparison?.warnings.map((warning) => <Warning key={warning}>{warning}</Warning>)}
          {error && (
            <div role="alert" className="mb-6 flex items-start gap-3 rounded-lg bg-red-50 p-4 text-sm text-red-700">
              <FiAlertCircle className="mt-0.5 shrink-0" />
              <span className="flex-1">{error}</span>
              <button type="button" onClick={retry} className="shrink-0 font-semibold underline">
                Spróbuj ponownie
              </button>
            </div>
          )}
          {!comparison && !error && (
            <div className="mb-6 rounded-xl border border-gray-200 bg-white p-8 text-center text-gray-500">
              Liczymy rachunki taryf...
            </div>
          )}
          {comparison && (
            <>
              <TariffSummaryCards comparison={comparison} />
              <TariffMatrix comparison={comparison} chosenKey={shownKey} onChoose={setChosenKey} />
            </>
          )}
          {(comparison || error) && (
            <TariffDayChart
              results={results}
              comparison={comparison}
              chosenKey={shownKey}
              failed={Boolean(dataError) && !isLoadingData}
              onRetry={reloadData}
            />
          )}
          {comparison && shownEntry && <TariffBillDetails entry={shownEntry} comparison={comparison} />}
        </div>
      )}
    </div>
  );
}

export default TariffsPage;
