import { formatChartLabel } from "../utils/energyFiles";

// Wspólny tooltip wykresów: ramka i opis czasu; `render` dostaje payload i rysuje wartości wykresu.
function ChartTooltip({ active, payload, label, resolution, render }) {
  if (!active || !payload?.length) return null;

  return (
    <div className="bg-white p-3 md:p-4 border border-gray-100 shadow-xl rounded-lg min-w-[150px] md:min-w-[180px]">
      <p className="text-gray-500 font-medium text-sm mb-2">{formatChartLabel(label, resolution)}</p>
      {render(payload)}
    </div>
  );
}

export default ChartTooltip;
