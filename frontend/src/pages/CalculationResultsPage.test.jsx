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

describe("CalculationResultsPage", () => {
  it.each([ALL_FILES_ID, ALL_DEVICE_FILES_ID])("dla źródła zbiorczego %s prosi o wybór pliku", async (sourceId) => {
    const get = vi.spyOn(apiClient, "get");

    renderWithSource(sourceId);

    expect(await screen.findByRole("link", { name: "Wybierz plik" })).toBeTruthy();
    expect(get).not.toHaveBeenCalled();
  });
});
