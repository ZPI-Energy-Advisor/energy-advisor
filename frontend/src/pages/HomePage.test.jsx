import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import apiClient from "../api/client";
import HomePage from "./HomePage";
import { CurrentUserContext } from "../context/currentUserContext";
import { EnergyFileContext } from "../context/energyFileContext";

const CONNECTED = {
  connected: true,
  connected_at: "2026-11-08T20:00:00Z",
  devices_count: 3,
  sync: { status: "synced", synced_at: "2026-11-08T20:00:00Z", error: null },
};
const DISCONNECTED = { ...CONNECTED, connected: false, connected_at: null, devices_count: 0 };

const LAMP = {
  device_id: "dev_lamp_01",
  device_name: "Lampa salon",
  device_type: "light",
  device_category: "Oświetlenie",
  flexibility_mode: "fixed",
  programs: [],
  state: "off",
  program_id: null,
  program_started_at: null,
  program_ends_at: null,
  power_kw: 0,
  energy_today_kwh: 0,
};
const WASHER = {
  ...LAMP,
  device_id: "dev_wm_01",
  device_name: "Pralka Bosch",
  device_type: "washing_machine",
  device_category: "AGD",
  flexibility_mode: "shiftable",
  programs: [
    { program_id: "cotton_60", program_name: "Bawełna 60°C", duration_min: 120 },
    { program_id: "quick_30", program_name: "Szybkie 30°C", duration_min: 30 },
  ],
  state: "idle",
};
const STATE = {
  hub_available: true,
  simulation_id: "sim_1",
  clock: { sim_time: "2026-10-19T12:00:00+02:00", running: false, speed: 288 },
  power: { consumption_kw: 1.8, production_kw: 3, net_kw: -1.2 },
  devices: [LAMP, WASHER],
  today: {
    day_start: "2026-10-19T00:00:00+02:00",
    until: "2026-10-19T12:00:00+02:00",
    consumption_kwh: 6.42,
    production_kwh: 9,
    net_kwh: -2.58,
    grid_import_kwh: 4.1,
    cost_pln: 3.7215,
    cost_error: null,
  },
};

const PLAN_RUN = {
  id: "run-1",
  plan_id: "plan-1",
  plan_date: "2026-10-19",
  status: "running",
  simulation_id: "sim_1",
  started_at: "2026-11-15T10:00:00Z",
  ended_at: null,
  sim_time: "2026-10-19T12:00:00+02:00",
  horizon_start: "2026-10-19T00:00:00+02:00",
  horizon_end: "2026-10-20T06:00:00+02:00",
  history_day: "2026-10-12",
  replay: { actions: 2, devices: 2, skipped_devices: [], rejected_actions: 0 },
  replayed_devices: [
    { device_id: "dev_pv_01", device_name: "Instalacja PV", history_day: "2026-10-12", history_kwh: -6.4, actual_kwh: -1.2 },
    { device_id: "dev_hp_01", device_name: "Pompa ciepła", history_day: "2026-10-12", history_kwh: 9.5, actual_kwh: 4.1 },
  ],
  planned_kwh: 6.4,
  actual_kwh: 0.6,
  devices: [
    {
      device_id: "dev_wm_01", device_name: "Pralka Bosch", kind: "program", planned_kwh: 1.4, actual_kwh: 0.6,
      actions: [{
        action_id: "dev_wm_01", device_id: "dev_wm_01", device_name: "Pralka Bosch", kind: "program",
        label: "Bawełna 60°C", start: "2026-10-19T11:45:00+02:00", end: "2026-10-19T12:30:00+02:00",
        energy_kwh: 1.4, status: "scheduled", code: null, detail: null,
      }],
    },
    {
      device_id: "dev_ev_01", device_name: "Ładowarka EV", kind: "ev", planned_kwh: 5, actual_kwh: 0,
      actions: [{
        action_id: "dev_ev_01", device_id: "dev_ev_01", device_name: "Ładowarka EV", kind: "ev", label: "5 kWh",
        start: "2026-10-19T22:00:00+02:00", end: "2026-10-20T03:00:00+02:00", energy_kwh: 5,
        status: "rejected", code: "device_not_found", detail: "Nie ma urządzenia w rejestrze",
      }],
    },
  ],
  errors: [{
    device_id: "dev_lamp_01", device_name: "Lampa salon", sim_time: "2026-10-19T08:15:00+02:00",
    code: "device_unreachable", message: "Brak odpowiedzi urządzenia",
  }],
};

const mockApi = ({ connection = CONNECTED, states = [STATE], planRun = null } = {}) => {
  let calls = 0;
  return vi.spyOn(apiClient, "get").mockImplementation((url) => {
    if (url === "/home") return Promise.resolve({ data: connection });
    if (url === "/home/plan-runs/latest") return Promise.resolve({ data: planRun });
    if (url === "/home/state") {
      const next = states[Math.min(calls, states.length - 1)];
      calls += 1;
      return next instanceof Error ? Promise.reject(next) : Promise.resolve({ data: next });
    }
    return Promise.reject(new Error(`Nieoczekiwane żądanie ${url}`));
  });
};

const renderPage = ({ me = { home_owner: true } } = {}) =>
  render(
    <CurrentUserContext.Provider value={{ me, isReady: true, loadError: null }}>
      <EnergyFileContext.Provider value={{ files: [] }}>
        <MemoryRouter initialEntries={["/home"]}>
          <Routes>
            <Route path="/home" element={<HomePage />} />
            <Route path="/dashboard" element={<p>Dashboard</p>} />
          </Routes>
        </MemoryRouter>
      </EnergyFileContext.Provider>
    </CurrentUserContext.Provider>,
  );

const deviceRow = async (name) => screen.findByRole("listitem", { name });

describe("HomePage", () => {
  it("przed wczytaniem konta pokazuje ładowanie", () => {
    render(
      <CurrentUserContext.Provider value={{ me: null, isReady: false, loadError: null }}>
        <EnergyFileContext.Provider value={{ files: [] }}>
          <MemoryRouter initialEntries={["/home"]}>
            <HomePage />
          </MemoryRouter>
        </EnergyFileContext.Provider>
      </CurrentUserContext.Provider>,
    );

    expect(screen.getByRole("status").textContent).toBe("Ładowanie…");
  });

  it("innego użytkownika odsyła na dashboard bez pytania API domu", () => {
    const get = vi.spyOn(apiClient, "get");

    renderPage({ me: { home_owner: false } });

    expect(screen.getByText("Dashboard")).toBeTruthy();
    expect(get).not.toHaveBeenCalled();
  });

  it("pokazuje zegar, bilans i urządzenia pogrupowane po kategorii", async () => {
    mockApi();
    renderPage();

    expect((await screen.findByTestId("sim-time")).textContent).toBe("12:00");
    expect(screen.getByText("Pauza")).toBeTruthy();
    expect(screen.getByText("6,42 kWh")).toBeTruthy();
    expect(screen.getByText("3,72 zł")).toBeTruthy();
    // Bilans ujemny: dom oddaje nadwyżkę PV do sieci.
    expect(screen.getByText("Oddawanie do sieci")).toBeTruthy();

    const washer = await deviceRow("Pralka Bosch");
    expect(within(washer).getByText("Gotowe")).toBeTruthy();
    expect(washer.textContent).toContain("Pralka · Przesuwalny");
    expect(screen.getByRole("heading", { name: /AGD/ })).toBeTruthy();
    expect(screen.getByRole("heading", { name: /Oświetlenie/ })).toBeTruthy();
  });

  it("nie pyta o stan, dopóki dom nie jest podłączony", async () => {
    const get = mockApi({ connection: DISCONNECTED });
    renderPage();

    expect(await screen.findByRole("button", { name: "Podłącz dom" })).toBeTruthy();
    expect(get).not.toHaveBeenCalledWith("/home/state");
  });

  it("po odłączeniu domu chowa jego stan i przestaje o niego pytać", async () => {
    const get = mockApi();
    vi.spyOn(apiClient, "delete").mockResolvedValue({ data: DISCONNECTED });
    renderPage();
    await screen.findByTestId("sim-time");

    fireEvent.click(screen.getByRole("button", { name: "Odłącz dom" }));

    expect(await screen.findByRole("button", { name: "Podłącz dom" })).toBeTruthy();
    // Strona dowiaduje się o odłączeniu z efektu panelu, więc widok znika po kolejnym renderze.
    await waitFor(() => expect(screen.queryByTestId("sim-time")).toBeNull());
    expect(screen.queryByRole("region", { name: "Urządzenia" })).toBeNull();
    expect(get.mock.calls.filter(([url]) => url === "/home/state")).toHaveLength(1);
  });

  it("włączenie lampy wysyła polecenie i od razu pokazuje nowy stan i moc", async () => {
    const lampOn = { ...LAMP, state: "running", power_kw: 0.06 };
    mockApi({ states: [STATE, { ...STATE, devices: [lampOn, WASHER] }] });
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({ data: { status: "accepted", state: "running" } });
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Włącz: Lampa salon" }));

    const lamp = await deviceRow("Lampa salon");
    await waitFor(() => expect(within(lamp).getByText("Pracuje")).toBeTruthy());
    expect(within(lamp).getByText("0,06 kW")).toBeTruthy();
    expect(within(lamp).getByRole("button", { name: "Wyłącz: Lampa salon" })).toBeTruthy();
    expect(post).toHaveBeenCalledWith("/home/devices/dev_lamp_01/commands", { command: "on" });
  });

  it("uruchamia wybrany program urządzenia", async () => {
    mockApi();
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({ data: {} });
    renderPage();

    const washer = await deviceRow("Pralka Bosch");
    fireEvent.change(within(washer).getByRole("combobox", { name: "Program: Pralka Bosch" }), {
      target: { value: "quick_30" },
    });
    fireEvent.click(within(washer).getByRole("button", { name: "Uruchom program: Pralka Bosch" }));

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/home/devices/dev_wm_01/commands", {
        command: "start_program",
        program_id: "quick_30",
      }),
    );
  });

  it("pokazuje powód odrzucenia polecenia przez hub", async () => {
    mockApi();
    vi.spyOn(apiClient, "post").mockRejectedValue({ response: { data: { detail: "Trwa program urządzenia" } } });
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Włącz: Lampa salon" }));

    expect((await screen.findByRole("alert")).textContent).toBe("Lampa salon: Trwa program urządzenia");
  });

  it("startuje zegar i zmienia tempo", async () => {
    mockApi();
    const put = vi.spyOn(apiClient, "put").mockResolvedValue({ data: {} });
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Start" }));
    await waitFor(() => expect(put).toHaveBeenCalledWith("/home/clock", { running: true }));

    fireEvent.change(screen.getByRole("combobox", { name: "Tempo" }), { target: { value: "1440" } });
    await waitFor(() => expect(put).toHaveBeenCalledWith("/home/clock", { speed: 1440 }));
  });

  it("zaczyna wybraną dobę od północy, a przy działającym zegarze blokuje zmianę doby", async () => {
    mockApi();
    const put = vi.spyOn(apiClient, "put").mockResolvedValue({ data: {} });
    renderPage();

    const dayInput = await screen.findByLabelText("Doba symulacji");
    expect(dayInput.value).toBe("2026-10-19");
    fireEvent.change(dayInput, { target: { value: "2026-10-25" } });
    fireEvent.click(screen.getByRole("button", { name: "Zacznij dobę od północy" }));

    await waitFor(() => expect(put).toHaveBeenCalledWith("/home/clock", { day: "2026-10-25" }));
  });

  it("przy działającym zegarze nie pozwala zmienić doby", async () => {
    mockApi({ states: [{ ...STATE, clock: { ...STATE.clock, running: true } }] });
    renderPage();

    expect(await screen.findByRole("button", { name: "Pauza" })).toBeTruthy();
    expect(screen.getByLabelText("Doba symulacji").disabled).toBe(true);
    expect(screen.getByRole("button", { name: "Zacznij dobę od północy" }).disabled).toBe(true);
  });

  it("przy niedostępnym hubie pokazuje ostatnie zużycie bez sterowania", async () => {
    mockApi({ states: [{ ...STATE, hub_available: false, clock: null, power: null, devices: [] }] });
    renderPage();

    expect(await screen.findByText(/Hub Smart Home nie odpowiada/)).toBeTruthy();
    expect(screen.getByText("6,42 kWh")).toBeTruthy();
    expect(screen.queryByRole("region", { name: "Urządzenia" })).toBeNull();
    expect(screen.getByRole("button", { name: "Start" }).disabled).toBe(true);
  });

  it("pokazuje, o której zegar sam stanie na końcu planu", async () => {
    mockApi({ states: [{ ...STATE, clock: { ...STATE.clock, running: true, stop_at: "2026-10-20T06:00:00+02:00" } }] });
    renderPage();

    expect(await screen.findByText("Zegar sam stanie o 06:00, na końcu planu dnia.")).toBeTruthy();
  });

  it("bez przebiegu planu nie pokazuje jego karty", async () => {
    mockApi();
    renderPage();

    expect(await screen.findByTestId("sim-time")).toBeTruthy();
    expect(screen.queryByRole("region", { name: "Przebieg planu" })).toBeNull();
  });

  it("pokazuje przebieg planu: energię z planu i symulacji, odrzucone komendy i awarie", async () => {
    mockApi({ planRun: PLAN_RUN });
    renderPage();

    const card = await screen.findByRole("region", { name: "Przebieg planu" });
    expect(within(card).getByText("Plan w trakcie")).toBeTruthy();
    expect(card.textContent).toContain("Urządzenia z planu zużyły 0,60 kWh z 6,40 kWh według planu.");
    const washer = within(card).getByRole("listitem", { name: "Pralka Bosch" });
    expect(washer.textContent).toContain("0,60 kWh / 1,40 kWh");
    expect(washer.textContent).toContain("Bawełna 60°C: Zaplanowane na 11:45–12:30");
    const ev = within(card).getByRole("listitem", { name: "Ładowarka EV" });
    expect(ev.textContent).toContain("Odrzucone: Nie ma urządzenia w rejestrze");
    expect(within(card).getByRole("alert").textContent).toContain("08:15 Lampa salon: Brak odpowiedzi urządzenia");
    const history = within(card).getByRole("region", { name: "Z dnia referencyjnego" });
    expect(history.textContent).toContain("Pracują same, tak jak 12 października 2026:");
    // PV na plusie, z dopiskiem „produkcji”.
    expect(history.textContent).toContain("Instalacja PV: 1,20 kWh z 6,40 kWh produkcji");
    expect(history.textContent).toContain("Pompa ciepła: 4,10 kWh z 9,50 kWh");
  });

  it("podaje dzień przy urządzeniu, gdy urządzenia mają różne dni referencyjne, i nie pokazuje -0", async () => {
    const [pv, heatPump] = PLAN_RUN.replayed_devices;
    mockApi({ planRun: { ...PLAN_RUN, replayed_devices: [
      { ...pv, history_day: "2026-10-18", actual_kwh: -0 },
      heatPump,
    ] } });
    renderPage();

    const history = await screen.findByRole("region", { name: "Z dnia referencyjnego" });
    expect(history.textContent).toContain("Pracują same, tak jak w dniu referencyjnym:");
    expect(history.textContent).toContain("Instalacja PV (jak 18 października 2026): 0,00 kWh z 6,40 kWh produkcji");
    expect(history.textContent).toContain("Pompa ciepła (jak 12 października 2026)");
    expect(history.textContent).not.toContain("-0,00");
  });

  it("w trakcie przebiegu planu lista pokazuje cały dom, żeby włączać urządzenia stałe ręcznie", async () => {
    mockApi({ states: [{ ...STATE, devices: [LAMP, WASHER] }], planRun: PLAN_RUN });
    renderPage();

    const card = await screen.findByRole("region", { name: "Przebieg planu" });
    expect(card.textContent).toContain("Urządzenia stałe (światło, czajnik, TV…) włącza się ręcznie na liście niżej");
    const list = await screen.findByRole("region", { name: "Urządzenia" });
    expect(within(list).getByRole("listitem", { name: "Lampa salon" })).toBeTruthy();
    expect(within(list).getByRole("listitem", { name: "Pralka Bosch" })).toBeTruthy();
  });

  it("„Zakończ” zamyka przebieg planu i odświeża stan domu", async () => {
    const get = mockApi({ planRun: PLAN_RUN });
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({
      data: { ...PLAN_RUN, status: "ended", ended_at: "2026-11-15T10:05:00Z" },
    });
    renderPage();

    const card = await screen.findByRole("region", { name: "Przebieg planu" });
    const stateCalls = get.mock.calls.filter(([url]) => url === "/home/state").length;
    fireEvent.click(within(card).getByRole("button", { name: "Zakończ" }));

    expect(await within(card).findByText("Zakończony")).toBeTruthy();
    expect(post).toHaveBeenCalledWith("/home/plan-runs/run-1/end");
    expect(within(card).queryByRole("button", { name: "Zakończ" })).toBeNull();
    await waitFor(() =>
      expect(get.mock.calls.filter(([url]) => url === "/home/state").length).toBeGreaterThan(stateCalls));
  });

  it("pokazuje błąd pobrania stanu i pozwala ponowić", async () => {
    const failure = Object.assign(new Error("503"), { response: { data: { detail: "Symulacja Smart Home jest wyłączona." } } });
    mockApi({ states: [failure, STATE] });
    renderPage();

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Symulacja Smart Home jest wyłączona.");
    fireEvent.click(within(alert).getByRole("button", { name: "Spróbuj ponownie" }));

    expect(await screen.findByTestId("sim-time")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
