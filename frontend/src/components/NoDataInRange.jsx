import { useEnergyFiles } from "../hooks/useEnergyFiles";
import { formatDate } from "../utils/energyFiles";
import { EMPTY_CARD, buttonClass } from "./uiStyles";

function NoDataInRange() {
  const { selectedFile, dateRange, applyDateRange, isLoadingData } = useEnergyFiles();

  return (
    <div className={EMPTY_CARD}>
      <h3 className="text-xl font-bold text-gray-800 mb-2">Brak danych w wybranym zakresie</h3>
      <p className="text-gray-500 mb-6 text-sm md:text-base">
        Plik nie zawiera pomiarów z okresu {formatDate(dateRange?.from)} – {formatDate(dateRange?.to)}.
        Wybierz inny zakres dat.
      </p>
      <button
        type="button"
        onClick={() => applyDateRange({ from: selectedFile.data_start, to: selectedFile.data_end })}
        disabled={isLoadingData}
        className={`${buttonClass("primary", "lg")} w-full sm:w-auto disabled:cursor-wait`}
      >
        Pokaż cały okres
      </button>
    </div>
  );
}

export default NoDataInRange;
