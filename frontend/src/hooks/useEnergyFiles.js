import { useContext } from "react";
import { EnergyFileContext } from "../context/energyFileContext";

export function useEnergyFiles() {
  const context = useContext(EnergyFileContext);
  if (!context) {
    throw new Error("useEnergyFiles musi być użyty wewnątrz EnergyFileProvider");
  }
  return context;
}
