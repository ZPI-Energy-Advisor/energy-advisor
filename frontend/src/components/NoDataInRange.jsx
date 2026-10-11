import { useEnergyFiles } from "../hooks/useEnergyFiles";
import { formatDate } from "../utils/energyFiles";

function NoDataInRange() {
  const { selectedFile, dateRange, applyDateRange, isLoadingData } = useEnergyFiles();

  return (
    <div className="bg-white p-8 md:p-10 rounded-lg shadow-sm border border-emerald-100 text-center">
      <h3 className="text-xl font-bold text-gray-800 mb-2">Brak danych w wybranym zakresie</h3>
      <p className="text-gray-500 mb-6 text-sm md:text-base">
        Plik nie zawiera pomiarów z okresu {formatDate(dateRange?.from)} – {formatDate(dateRange?.to)}.
        Wybierz inny zakres dat.
      </p>
      <button
        type="button"
        onClick={() => applyDateRange({ from: selectedFile.data_start, to: selectedFile.data_end })}
        disabled={isLoadingData}
        className="inline-block bg-emerald-600 text-white font-medium px-6 py-3 rounded hover:bg-emerald-700 transition-colors w-full sm:w-auto disabled:opacity-60 disabled:cursor-wait"
      >
        Pokaż cały okres
      </button>
    </div>
  );
}

export default NoDataInRange;
