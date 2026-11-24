import { useMemo } from "react";
import { useEnergyFiles } from "./useEnergyFiles";

// Granice zakresu dat: cały okres wybranego pliku (albo null, gdy nie ma pliku).
export function useRangeBounds() {
  const { selectedFile } = useEnergyFiles();
  const dataStart = selectedFile?.data_start;
  const dataEnd = selectedFile?.data_end;
  return useMemo(() => (dataStart && dataEnd ? { from: dataStart, to: dataEnd } : null), [dataStart, dataEnd]);
}
