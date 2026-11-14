import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import apiClient from "../api/client";
import SchedulePage from "./SchedulePage";
import { EnergyFileContext } from "../context/energyFileContext";
import { SOURCE_TYPE_DEVICES } from "../utils/energyFiles";

const FILE = {
  id: "f1",
  file_name: "dom.json",
  source_type: SOURCE_TYPE_DEVICES,
  data_start: "2026-10-19",
  data_end: "2026-10-21",
};

const action = (overrides) => ({
  action_id: "act_1",
  device_id: "dev_wm",
  device_name: "Pralka",
  flexibility_mode: "shiftable",
  program_name: "Bawełna",
  original_start: "2026-10-19T18:00:00+02:00",
  original_end: "2026-10-19T19:00:00+02:00",
  start: "2026-10-19T13:00:00+02:00",
  end: "2026-10-19T14:00:00+02:00",
  energy_kwh: 1.5,
  cost_before: 1.5,
  cost_after: 0.3,
  status: "moved",
  reason: null,
  charging: null,
  ...overrides,
});

const SCHEDULE = {
  date_from: "2026-10-19",
  date_to: "2026-10-20",
  pricing: "PGE, G11",
  cost_before: 3.1,
  cost_after: 0.7,
  bill_before: null,
  bill_after: null,
  missing_price_actions: 0,
  missing_price_days: [],
  actions: [
    action(),
    action({
      action_id: "act_2", original_start: "2026-10-20T18:00:00+02:00", original_end: "2026-10-20T19:00:00+02:00",
      start: "2026-10-20T13:00:00+02:00", end: "2026-10-20T14:00:00+02:00", cost_before: 1.5, cost_after: 0.3,
    }),
    action({
      action_id: "act_tv", device_id: "dev_tv", device_name: "Telewizor", flexibility_mode: "fixed", program_name: null,
      original_start: "2026-10-19T20:00:00+02:00", original_end: "2026-10-19T21:00:00+02:00",
      start: "2026-10-19T20:00:00+02:00", end: "2026-10-19T21:00:00+02:00", energy_kwh: 0.2,
      cost_before: 0.1, cost_after: 0.1, status: "unchanged",
    }),
  ],
  prices: [{ start: "2026-10-19T00:00:00+02:00", price_pln_kwh: 1.0 }],
};

const renderPage = () =>
  render(
    <MemoryRouter>
      <EnergyFileContext.Provider
        value={{
          isReady: true,
          selectedFile: FILE,
          selectedFileId: FILE.id,
          files: [FILE],
          filesError: null,
          isLoadingFiles: false,
          reload: vi.fn(),
        }}
      >
        <SchedulePage />
      </EnergyFileContext.Provider>
    </MemoryRouter>,
  );

afterEach(() => vi.restoreAllMocks());

describe("SchedulePage", () => {
  it("ma tytuł optymalizacji historycznej i opis ekranu", () => {
    renderPage();

    expect(screen.getByRole("heading", { name: "Optymalizacja historyczna" })).toBeTruthy();
    expect(screen.getByText(/ile zaoszczędziłbyś w wybranym okresie z przeszłości/)).toBeTruthy();
  });

  it("kalendarz wybiera zakres dwoma kliknięciami, a przyciski cały okres i losowy dzień", () => {
    renderPage();
    const get = vi.spyOn(apiClient, "get").mockResolvedValue({ data: SCHEDULE });

    // Dni spoza pliku są wyłączone.
    expect(screen.getByLabelText("2026-10-18").disabled).toBe(true);
    fireEvent.click(screen.getByLabelText("2026-10-21"));
    fireEvent.click(screen.getByLabelText("2026-10-20"));
    expect(screen.getByText("20.10–21.10 (2 dni)")).toBeTruthy();

    fireEvent.click(screen.getByText("Cały okres pliku"));
    expect(screen.getByText("19.10–21.10 (3 dni)")).toBeTruthy();

    vi.spyOn(Math, "random").mockReturnValue(0.5);
    fireEvent.click(screen.getByText("Losowy dzień"));
    expect(screen.getByText("20.10, wtorek (1 dzień)")).toBeTruthy();

    fireEvent.click(screen.getByText("Pokaż wynik"));
    expect(get).toHaveBeenCalledWith("/energy-files/f1/schedule", { params: { from: "2026-10-20", to: "2026-10-20" } });
  });

  it("pokazuje jeden dzień naraz ze strzałkami, podsumowanie okresu i chowa urządzenia stałe", async () => {
    renderPage();
    vi.spyOn(apiClient, "get").mockResolvedValue({ data: SCHEDULE });

    fireEvent.click(screen.getByRole("button", { name: "Pokaż wynik" }));

    const browser = await screen.findByRole("region", { name: "Wyniki dzień po dniu" });
    expect(within(browser).getByText("Dzień 1 z 2")).toBeTruthy();
    // Telewizor (urządzenie stałe) nie ma wiersza na wykresie, jest tylko w zwiniętej informacji.
    expect(within(browser).queryByText("Telewizor")).toBeNull();
    expect(screen.getByText(/Urządzenia stałe \(1\) zostają o swoich godzinach/)).toBeTruthy();

    fireEvent.click(within(browser).getByRole("button", { name: "Następny dzień" }));
    expect(within(browser).getByText("Dzień 2 z 2")).toBeTruthy();

    const summary = screen.getByRole("region", { name: "Podsumowanie okresu" });
    const total = within(summary).getByText("Razem").closest("tr");
    expect(within(total).getByText("2,40 zł")).toBeTruthy();
    fireEvent.click(within(summary).getByRole("button", { name: "19.10, poniedziałek" }));
    expect(within(browser).getByText("Dzień 1 z 2")).toBeTruthy();
  });
});
