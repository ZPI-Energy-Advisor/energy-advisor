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

const renderPage = (file = FILE) =>
  render(
    <MemoryRouter>
      <EnergyFileContext.Provider
        value={{
          isReady: true,
          selectedFile: file,
          selectedFileId: file.id,
          files: [file],
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
  it("plik urządzeń bez odczytów nie wysypuje strony, tylko mówi, że nie ma okresu", () => {
    renderPage({ ...FILE, data_start: null, data_end: null });

    expect(screen.getByText(/nie ma odczytów zużycia, więc nie ma okresu do optymalizacji/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Pokaż wynik" })).toBeNull();
  });

  it("przesunięcie na następny dzień pokazuje datę w kolumnie Po", async () => {
    renderPage();
    const ev = action({
      action_id: "act_ev", device_id: "dev_ev", device_name: "Ładowarka EV", program_name: null,
      flexibility_mode: "interruptible",
      original_start: "2026-10-19T18:00:00+02:00", original_end: "2026-10-19T21:00:00+02:00",
      start: "2026-10-20T01:00:00+02:00", end: "2026-10-20T04:00:00+02:00",
    });
    vi.spyOn(apiClient, "get").mockResolvedValue({ data: { ...SCHEDULE, actions: [ev] } });

    fireEvent.click(screen.getByRole("button", { name: "Pokaż wynik" }));

    const browser = await screen.findByRole("region", { name: "Wyniki dzień po dniu" });
    const row = within(browser).getByText("Ładowarka EV", { selector: "td" }).closest("tr");
    expect(within(row).getByText("20.10 01:00–04:00")).toBeTruthy();
  });
});

describe("SchedulePage: taryfa", () => {
  const PROFILE = { base_info: { distribution_operator: "PGE" }, consumption_and_tariff: { tariff_type: "G12", dynamic_price: false } };
  const OPTIONS = {
    tariffs: [{ code: "G11" }, { code: "G12" }, { code: "G12w" }],
    dynamic_offer: { distribution_groups: ["G11", "G12"] },
  };
  const G11_RESULT = { ...SCHEDULE, tariff_group: "G11", tariff_dynamic: false, prosumer: false, cost_before: 3.1, cost_after: 3.1 };

  const mockApi = (schedule, profile = PROFILE) =>
    vi.spyOn(apiClient, "get").mockImplementation(async (url) => {
      if (url === "/users/me/profile") return { data: profile };
      if (url === "/tariffs/options") return { data: OPTIONS };
      return { data: schedule };
    });

  it("domyślnie taryfa z profilu, a wybrana inna idzie w zapytaniu", async () => {
    const get = mockApi(SCHEDULE);
    renderPage();

    const group = await screen.findByLabelText("Grupa taryfowa");
    expect(group.value).toBe("G12");
    expect(screen.getByText(/Taryfa z Twojego profilu/)).toBeTruthy();

    fireEvent.change(group, { target: { value: "G11" } });
    fireEvent.click(screen.getByRole("button", { name: "Z ceną dynamiczną" }));
    expect(screen.getByText(/Sprawdzasz inną taryfę niż w profilu \(G12\)/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Pokaż wynik" }));

    expect(get).toHaveBeenCalledWith("/energy-files/f1/schedule", {
      params: { from: "2026-10-19", to: "2026-10-19", tariff: "G11", dynamic: true },
    });
  });

  it("cena dynamiczna niedostępna dla grupy, której sprzedawca nie dopuszcza", async () => {
    mockApi(SCHEDULE);
    renderPage();

    fireEvent.change(await screen.findByLabelText("Grupa taryfowa"), { target: { value: "G12w" } });

    expect(screen.getByRole("button", { name: "Z ceną dynamiczną" }).disabled).toBe(true);
  });

  it("tylko oszczędność faktyczna, bez szacunku na miesiąc i rok", async () => {
    mockApi(SCHEDULE);
    renderPage();

    fireEvent.click(screen.getByRole("button", { name: "Pokaż wynik" }));

    expect((await screen.findAllByText("Oszczędność")).length).toBeGreaterThan(0);
    expect(screen.queryByText("Szacunek oszczędności")).toBeNull();
    expect(screen.queryByText(/rocznie/)).toBeNull();
  });

  it("G11: wyjaśnienie zerowej oszczędności i sprawdzenie ceny dynamicznej jednym kliknięciem", async () => {
    const get = mockApi(G11_RESULT);
    renderPage();
    await screen.findByLabelText("Grupa taryfowa");

    fireEvent.click(screen.getByRole("button", { name: "Pokaż wynik" }));

    expect(await screen.findByText(/W taryfie G11 prąd kosztuje tyle samo o każdej porze/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Sprawdź z ceną dynamiczną" }));

    expect(get).toHaveBeenLastCalledWith("/energy-files/f1/schedule", {
      params: { from: "2026-10-19", to: "2026-10-19", tariff: "G11", dynamic: true },
    });
  });

  it("wynik jest podpisany taryfą i okresem", async () => {
    mockApi({ ...SCHEDULE, tariff_group: "G12", tariff_dynamic: false });
    renderPage();
    await screen.findByLabelText("Grupa taryfowa");

    fireEvent.click(screen.getByRole("button", { name: "Pokaż wynik" }));

    expect(await screen.findByText(/^G12 · /)).toBeTruthy();
    expect(screen.getByText(/\(taryfa z profilu\)/)).toBeTruthy();
  });

  it("net-metering: bez ceny dynamicznej w wyborze i w podpowiedzi G11", async () => {
    const netMetering = {
      ...PROFILE,
      consumption_and_tariff: { tariff_type: "G11", dynamic_price: false },
      pv_config: { mode: "net_metering", power_of_pv_kwp: 5 },
    };
    mockApi({ ...G11_RESULT, prosumer: true }, netMetering);
    renderPage();
    await screen.findByLabelText("Grupa taryfowa");

    expect(screen.getByRole("button", { name: "Z ceną dynamiczną" }).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Pokaż wynik" }));

    const note = await screen.findByText(/W taryfie G11 prąd z sieci kosztuje tyle samo/);
    expect(note.textContent).not.toMatch(/ceną dynamiczną/);
    expect(screen.queryByRole("button", { name: "Sprawdź z ceną dynamiczną" })).toBeNull();
  });
});
