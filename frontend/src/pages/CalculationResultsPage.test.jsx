import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import apiClient from "../api/client";
import CalculationResultsPage from "./CalculationResultsPage";
import { EnergyFileContext } from "../context/energyFileContext";
import { ALL_DEVICE_FILES_ID, ALL_FILES_ID } from "../utils/energyFiles";

const renderWithSource = (sourceId) =>
  render(
    <MemoryRouter>
      <EnergyFileContext.Provider
        value={{
          isReady: true,
          selectedFile: { id: sourceId, file_name: "Wszystkie pliki" },
          selectedFileId: sourceId,
          files: [{ id: "f1", status: "completed" }],
          filesError: null,
          isLoadingFiles: false,
          reload: vi.fn(),
        }}
      >
        <CalculationResultsPage />
      </EnergyFileContext.Provider>
    </MemoryRouter>,
  );

const cycle = {
  cycle_start: "2026-10-01T00:00:00",
  cycle_end: "2026-11-30T00:00:00",
  days_billed: 30,
  days_in_cycle: 61,
  active_energy_net: 300,
  variable_network_net: 120,
  quality_net: 6.5,
  renewable_net: 0,
  cogeneration_net: 2,
  fixed_network_net: 8.36,
  subscription_net: 2.46,
  capacity_net: 7.38,
  transition_net: 0.98,
  vat: 103.86,
  gross_total: 551.4,
};

const calculation = {
  tariff_data: { tariff_type: "G11" },
  annual_consumption: { annual_kwh: 7300, days: 30, scaled: true },
  tariff_calculations: { G11: { gross_total: 551.4, deposit_amount: 0, payable_gross: 551.4, active_energy_gross: 369 } },
  tariff_calculation: {
    cycles: [cycle],
    gross_total: 551.4,
    payable_gross: 551.4,
    deposit_amount: 0,
    deposit_applied: 0,
    active_energy_gross: 369,
  },
};

const renderSingleFile = () =>
  render(
    <MemoryRouter>
      <EnergyFileContext.Provider
        value={{
          isReady: true,
          selectedFile: { id: "f1", file_name: "dom.json", source_type: "devices" },
          selectedFileId: "f1",
          files: [{ id: "f1", status: "completed" }],
          results: null,
          isLoadingData: false,
          dataError: null,
          clearDataError: vi.fn(),
        }}
      >
        <CalculationResultsPage />
      </EnergyFileContext.Provider>
    </MemoryRouter>,
  );

describe("CalculationResultsPage", () => {
  it("pokazuje każdą opłatę osobno i rozliczenie części okresu", async () => {
    vi.spyOn(apiClient, "get").mockResolvedValue({ data: calculation });

    renderSingleFile();

    expect(await screen.findByText(/opłaty miesięczne za 30 z 61 dni/)).toBeTruthy();
    for (const label of ["Opłata jakościowa", "Opłata OZE", "Opłata kogeneracyjna", "Opłata mocowa", "Opłata przejściowa"]) {
      expect(screen.getByRole("columnheader", { name: label })).toBeTruthy();
    }
    expect(screen.getByText("przeskalowane z 30 dni pliku")).toBeTruthy();
  });

  it.each([ALL_FILES_ID, ALL_DEVICE_FILES_ID])("dla źródła zbiorczego %s prosi o wybór pliku", async (sourceId) => {
    const get = vi.spyOn(apiClient, "get");

    renderWithSource(sourceId);

    expect(await screen.findByRole("link", { name: "Wybierz plik" })).toBeTruthy();
    expect(get).not.toHaveBeenCalled();
  });
});
