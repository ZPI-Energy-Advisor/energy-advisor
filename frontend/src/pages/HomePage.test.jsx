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

// Rachunek przed i po (ZP-114) w kształcie PlanRunCostOut.
const COST = {
  complete: true,
  until: "2026-10-20T06:00:00+02:00",
  cost_before: 6.4,
  cost_after: 1.9,
  planned_cost: 1.78,
  saving: 4.5,
  saving_percent: 70.3,
  devices: [{
    device_id: "dev_wm_01", device_name: "Pralka Bosch", kind: "program", energy_before_kwh: 1.4,
    energy_after_kwh: 1.4, cost_before: 1.2, planned_cost: 0.4, cost_after: 0.42, saving: 0.78,
  }],
  excluded: [{ device_id: "dev_ev_01", device_name: "Ładowarka EV" }],
  pending: [],
  manual: [{ device_id: "dev_lamp_01", device_name: "Lampa salon", energy_kwh: 0.2, cost: 0.12 }],
  manual_cost: 0.12,
  pv: { production_kwh: 6.4, self_consumption_kwh: 3.1, plan_from_pv_kwh: 0.9, plan_kwh: 1.4 },
  deviations: [
    {
      kind: "interrupted", device_id: "dev_ev_01", device_name: "Ładowarka EV", sim_time: "2026-10-19T23:00:00+02:00",
      end: null, message: "Wyłączone ręcznie w trakcie pracy.", excluded: true,
    },
    {
      kind: "grid_limit", device_id: null, device_name: null, sim_time: "2026-10-19T19:00:00+02:00",
      end: "2026-10-19T19:30:00+02:00", message: "Pobór z sieci do 4,40 kW, a limit przyłącza to 3,00 kW.",
      excluded: false,
    },
  ],
};

const mockApi = ({ connection = CONNECTED, states = [STATE], planRun = null, history = [], reports = {} } = {}) => {
  let calls = 0;
  return vi.spyOn(apiClient, "get").mockImplementation((url) => {
    if (url === "/home") return Promise.resolve({ data: connection });
    if (url === "/home/plan-runs/latest") return Promise.resolve({ data: planRun });
    if (url === "/home/plan-runs") return Promise.resolve({ data: history });
    if (url.startsWith("/home/plan-runs/") && reports[url.split("/").pop()]) {
      return Promise.resolve({ data: reports[url.split("/").pop()] });
    }
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
const showList = async () => fireEvent.click(await screen.findByRole("button", { name: "Lista" }));

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

    await showList();
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
    await showList();

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
    await showList();

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
    await showList();

    fireEvent.click(await screen.findByRole("button", { name: "Włącz: Lampa salon" }));

    expect((await screen.findByRole("alert")).textContent).toBe("Lampa salon: Trwa program urządzenia");
  });

  it("startuje zegar i zmienia tempo", async () => {
    mockApi();
    const put = vi.spyOn(apiClient, "put").mockResolvedValue({ data: {} });
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Start" }));
    await waitFor(() => expect(put).toHaveBeenCalledWith("/home/clock", { running: true }));

    const slider = screen.getByRole("slider", { name: /Tempo/ });
    expect(slider.getAttribute("aria-valuetext")).toBe("doba w 5 min");
    // Przeciąganie przez kilka progów wysyła jedno polecenie, z tempem z ostatniego progu.
    fireEvent.change(slider, { target: { value: "6" } });
    fireEvent.change(slider, { target: { value: "7" } });
    expect(slider.getAttribute("aria-valuetext")).toBe("doba w minutę");
    await waitFor(() => expect(put).toHaveBeenCalledWith("/home/clock", { speed: 1440 }));
    expect(put.mock.calls.filter(([, body]) => body.speed)).toHaveLength(1);
  });

  it("przy tempie spoza progów puszczenie suwaka wybiera próg, na którym stoi", async () => {
    mockApi({ states: [{ ...STATE, clock: { ...STATE.clock, speed: 100 } }] });
    const put = vi.spyOn(apiClient, "put").mockResolvedValue({ data: {} });
    renderPage();

    const slider = await screen.findByRole("slider", { name: /Tempo/ });
    expect(slider.getAttribute("aria-valuetext")).toBe("doba w 14 min");
    fireEvent.pointerUp(slider);

    expect(slider.getAttribute("aria-valuetext")).toBe("doba w 12 min");
    await waitFor(() => expect(put).toHaveBeenCalledWith("/home/clock", { speed: 120 }));
  });

  it("przy końcu planu w zegarze podaje, ile to potrwa naprawdę", async () => {
    mockApi({ states: [{ ...STATE, clock: { ...STATE.clock, running: true, stop_at: "2026-10-20T06:00:00+02:00" } }] });
    renderPage();

    // 18 h symulacji przy dobie w 5 min (288×) to 225 s.
    expect(await screen.findByText("koniec planu za ok. 4 min")).toBeTruthy();
  });

  it("nie ma ręcznego wyboru doby: dobę ustawia uruchomienie planu", async () => {
    mockApi();
    renderPage();

    expect(await screen.findByTestId("sim-time")).toBeTruthy();
    expect(screen.queryByLabelText("Doba symulacji")).toBeNull();
    expect(screen.queryByRole("button", { name: "Zacznij dobę od północy" })).toBeNull();
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

  it("w trakcie przebiegu pokazuje plan w zegarze, a godziny planu przy urządzeniach", async () => {
    mockApi({
      states: [{ ...STATE, devices: [LAMP, WASHER, { ...LAMP, device_id: "dev_pv_01", device_name: "Instalacja PV" }] }],
      planRun: PLAN_RUN,
    });
    renderPage();

    const bar = await screen.findByRole("region", { name: "Przebieg planu" });
    expect(bar.textContent).toContain("Plan na 19 października · w trakcie, do 06:00 następnego dnia");
    expect(within(bar).getByRole("button", { name: "Zakończ" })).toBeTruthy();
    // Czas jest tylko w zegarze: bez osobnej karty planu i bez drugiej godziny zatrzymania.
    expect(screen.queryByText(/Zegar sam stanie/)).toBeNull();
    expect(screen.queryByRole("region", { name: "Rachunek przed i po" })).toBeNull();

    await showList();
    const list = await screen.findByRole("region", { name: "Urządzenia" });
    // Pralka pracuje: zegar 12:00, plan 11:45–12:30.
    expect(within(list).getByRole("listitem", { name: "Pralka Bosch" }).textContent).toContain("Plan 11:45–12:30 · w trakcie");
    // Urządzenia z historii bez plakietki planu: ich stan jest na liście, a dzień referencyjny w raporcie.
    expect(within(list).getByRole("listitem", { name: "Instalacja PV" }).textContent).not.toContain("października");
    // Urządzenia stałe bez plakietki, z przyciskiem do ręcznego włączenia.
    const lamp = within(list).getByRole("listitem", { name: "Lampa salon" });
    expect(lamp.textContent).not.toContain("Plan");
    expect(within(lamp).getByRole("button", { name: "Włącz: Lampa salon" })).toBeTruthy();
  });

  it("w trakcie przebiegu odchylenia są paskiem pod zegarem", async () => {
    mockApi({ planRun: { ...PLAN_RUN, cost: { ...COST, complete: false } } });
    renderPage();

    const alert = await screen.findByRole("alert", { name: "Odchylenia od planu" });
    expect(alert.textContent).toContain("19:00–19:30 Limit przyłącza: Pobór z sieci do 4,40 kW");
  });

  it("po zakończeniu planu zegar pokazuje wynik, a „Zobacz raport” otwiera go w zakładce „Raporty”", async () => {
    const done = { ...PLAN_RUN, status: "completed", cost: COST };
    const get = mockApi({
      planRun: done,
      history: [{ id: "run-1", plan_date: "2026-10-19", status: "completed", started_at: "2026-11-15T10:00:00Z",
        ended_at: "2026-11-15T10:06:00Z", complete: true, cost_before: 6.4, cost_after: 1.9, saving: 4.5,
        saving_percent: 70.3, deviations: 2 }],
      reports: { "run-1": done },
    });
    renderPage();

    const bar = await screen.findByRole("region", { name: "Przebieg planu" });
    expect(bar.textContent).toContain("Plan na 19 października wykonany · oszczędność 4,50 zł (70,3%)");
    expect(within(bar).queryByRole("button", { name: "Zakończ" })).toBeNull();
    // Po końcu planu bez plakietek przy urządzeniach i bez paska odchyleń.
    await showList();
    expect((await screen.findByRole("region", { name: "Urządzenia" })).textContent).not.toContain("Plan 11:45");
    expect(screen.queryByRole("alert", { name: "Odchylenia od planu" })).toBeNull();

    fireEvent.click(within(bar).getByRole("button", { name: "Zobacz raport" }));

    expect(screen.getByRole("tab", { name: "Raporty" }).getAttribute("aria-selected")).toBe("true");
    const report = await screen.findByRole("region", { name: "Rachunek przed i po" });
    expect(report.textContent).toContain("Oszczędność4,50 zł");
    expect(get).toHaveBeenCalledWith("/home/plan-runs/run-1");

    // Ręczny powrót do „Raportów” nie otwiera znowu tego samego raportu.
    fireEvent.click(screen.getByRole("tab", { name: "Symulacja" }));
    fireEvent.click(screen.getByRole("tab", { name: "Raporty" }));
    const history = await screen.findByRole("region", { name: "Historia przebiegów" });
    expect(within(history).getByRole("button", { name: "Pokaż raport" })).toBeTruthy();
    expect(within(history).queryByRole("region", { name: "Rachunek przed i po" })).toBeNull();
  });

  it("po końcu planu „Start” jest wyłączony, a „Uruchom ponownie” zaczyna ten sam plan od nowa", async () => {
    mockApi({ planRun: { ...PLAN_RUN, status: "completed", cost: COST } });
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({ data: { ...PLAN_RUN, id: "run-2" } });
    renderPage();

    const bar = await screen.findByRole("region", { name: "Przebieg planu" });
    const start = screen.getByRole("button", { name: "Start" });
    expect(start.disabled).toBe(true);
    expect(screen.getByText(/Plan na 19 października się skończył/)).toBeTruthy();

    fireEvent.click(within(bar).getByRole("button", { name: "Uruchom ponownie" }));

    await waitFor(() => expect(post).toHaveBeenCalledWith("/home/plan-runs", { plan_id: "plan-1" }));
    // Nowy przebieg trwa: pasek ma znowu „Zakończ”.
    expect(await within(bar).findByRole("button", { name: "Zakończ" })).toBeTruthy();
  });

  it("„Start” działa, gdy hub ma już inną symulację niż zakończony plan", async () => {
    mockApi({ planRun: { ...PLAN_RUN, status: "completed", simulation_id: "sim_old", cost: COST } });
    renderPage();

    await screen.findByRole("region", { name: "Przebieg planu" });

    expect(screen.getByRole("button", { name: "Start" }).disabled).toBe(false);
  });

  it("po „Zakończ” pasek mówi, że rachunek jest niepełny", async () => {
    mockApi({ planRun: { ...PLAN_RUN, status: "ended", cost: { ...COST, complete: false } } });
    renderPage();

    const bar = await screen.findByRole("region", { name: "Przebieg planu" });
    expect(bar.textContent).toContain("zakończony przed czasem · oszczędność 4,50 zł (70,3%), niepełny");
  });

  it("przebieg bez rachunku pokazuje awarie urządzeń w pasku pod zegarem", async () => {
    mockApi({ planRun: PLAN_RUN });
    renderPage();

    const alert = await screen.findByRole("alert", { name: "Odchylenia od planu" });
    expect(alert.textContent).toContain("08:15 Awaria – Lampa salon: Brak odpowiedzi urządzenia");
  });

  it("przerwany przebieg mówi, że symulacja zaczęła inną dobę", async () => {
    mockApi({ planRun: { ...PLAN_RUN, status: "superseded" } });
    renderPage();

    const bar = await screen.findByRole("region", { name: "Przebieg planu" });
    expect(bar.textContent).toContain("Plan na 19 października przerwany: symulacja zaczęła inną dobę.");
  });

  it("zakładka „Raporty” pokazuje przebiegi i otwiera raport wybranego", async () => {
    const previous = {
      id: "run-0", plan_date: "2026-10-18", status: "completed", started_at: "2026-11-14T10:00:00Z",
      ended_at: "2026-11-14T10:06:00Z", complete: true, cost_before: 6.4, cost_after: 1.9, saving: 4.5,
      saving_percent: 70.3, deviations: 2,
    };
    const get = mockApi({
      planRun: PLAN_RUN,
      history: [{ ...previous, id: "run-1", plan_date: "2026-10-19", status: "running", saving: null }, previous],
      reports: { "run-0": { ...PLAN_RUN, id: "run-0", plan_date: "2026-10-18", status: "completed", cost: COST } },
    });
    renderPage();

    // Na zakładce symulacji historii nie ma.
    await screen.findByRole("region", { name: "Przebieg planu" });
    expect(screen.queryByRole("region", { name: "Historia przebiegów" })).toBeNull();
    fireEvent.click(screen.getByRole("tab", { name: "Raporty" }));

    const history = await screen.findByRole("region", { name: "Historia przebiegów" });
    expect(within(history).getAllByRole("listitem")).toHaveLength(2);
    expect(within(history).getByRole("listitem", { name: /19 października/ }).textContent).toContain("rachunek po zakończeniu");
    const entry = within(history).getByRole("listitem", { name: /18 października/ });
    expect(entry.textContent).toContain("wykonany");
    expect(entry.textContent).toContain("oszczędność 4,50 zł (70,3%) · odchylenia: 2");

    fireEvent.click(within(entry).getByRole("button", { name: "Pokaż raport" }));

    const report = await within(entry).findByRole("region", { name: "Rachunek przed i po" });
    expect(report.textContent).toContain("Oszczędność4,50 zł");
    expect(get).toHaveBeenCalledWith("/home/plan-runs/run-0");
    // Rozwinięty raport nie powtarza streszczenia z wiersza.
    expect(entry.textContent).not.toContain("oszczędność 4,50 zł (70,3%)");
    // Raport jest tylko do odczytu.
    expect(within(entry).queryByRole("button", { name: "Zakończ" })).toBeNull();
  });

  it("błąd jednego raportu znika po otwarciu innego", async () => {
    const entry = (id, day) => ({
      id, plan_date: day, status: "completed", started_at: "2026-11-14T10:00:00Z", ended_at: "2026-11-14T10:06:00Z",
      complete: true, cost_before: 6.4, cost_after: 1.9, saving: 4.5, saving_percent: 70.3, deviations: 0,
    });
    mockApi({
      history: [entry("run-a", "2026-10-18"), entry("run-b", "2026-10-17")],
      reports: { "run-b": { ...PLAN_RUN, id: "run-b", status: "completed", cost: COST } },
    });
    renderPage();
    fireEvent.click(await screen.findByRole("tab", { name: "Raporty" }));
    const history = await screen.findByRole("region", { name: "Historia przebiegów" });

    // Raportu run-a nie ma w API: błąd.
    fireEvent.click(within(within(history).getByRole("listitem", { name: /18 października/ })).getByRole("button", { name: "Pokaż raport" }));
    expect(await within(history).findByRole("alert")).toBeTruthy();

    fireEvent.click(within(within(history).getByRole("listitem", { name: /17 października/ })).getByRole("button", { name: "Pokaż raport" }));
    expect(await within(history).findByRole("region", { name: "Rachunek przed i po" })).toBeTruthy();
    expect(within(history).queryByText("Nie udało się pobrać raportu przebiegu.")).toBeNull();
  });

  it("„Zobacz raport” przebiegu spoza listy mówi, że go nie ma", async () => {
    mockApi({
      planRun: { ...PLAN_RUN, status: "completed", cost: COST },
      history: [{ id: "run-0", plan_date: "2026-10-18", status: "completed", started_at: "2026-11-14T10:00:00Z",
        ended_at: null, complete: true, cost_before: 1, cost_after: 1, saving: 0, saving_percent: 0, deviations: 0 }],
    });
    renderPage();

    const bar = await screen.findByRole("region", { name: "Przebieg planu" });
    fireEvent.click(within(bar).getByRole("button", { name: "Zobacz raport" }));

    const history = await screen.findByRole("region", { name: "Historia przebiegów" });
    expect((await within(history).findByRole("alert")).textContent).toBe("Nie ma tego przebiegu na liście raportów.");
  });

  it("raporty są dostępne bez podłączonego domu", async () => {
    mockApi({ connection: DISCONNECTED });
    renderPage();

    fireEvent.click(await screen.findByRole("tab", { name: "Raporty" }));

    const history = await screen.findByRole("region", { name: "Historia przebiegów" });
    expect(history.textContent).toContain("Nie ma jeszcze raportów.");
  });

  it("„Zakończ” zamyka przebieg planu i odświeża stan domu", async () => {
    const get = mockApi({ planRun: PLAN_RUN });
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({
      data: { ...PLAN_RUN, status: "ended", ended_at: "2026-11-15T10:05:00Z", cost: { ...COST, complete: false } },
    });
    renderPage();

    const bar = await screen.findByRole("region", { name: "Przebieg planu" });
    const stateCalls = get.mock.calls.filter(([url]) => url === "/home/state").length;
    fireEvent.click(within(bar).getByRole("button", { name: "Zakończ" }));

    expect(await within(bar).findByText(/zakończony przed czasem/)).toBeTruthy();
    expect(post).toHaveBeenCalledWith("/home/plan-runs/run-1/end");
    expect(within(bar).queryByRole("button", { name: "Zakończ" })).toBeNull();
    await waitFor(() =>
      expect(get.mock.calls.filter(([url]) => url === "/home/state").length).toBeGreaterThan(stateCalls));
  });

  it("nad bilansem podaje okres doby i że dotyczy całego domu", async () => {
    mockApi();
    renderPage();

    const summary = await screen.findByRole("region", { name: "Podsumowanie domu" });
    expect(within(summary).getByRole("heading", { name: "Bilans doby · cały dom" })).toBeTruthy();
    expect(summary.textContent).toContain("19 października, 00:00–12:00");
    expect(summary.textContent).toContain("Cały dom: energia pobrana z sieci (po PV)");
  });

  it("w przebiegu planu po północy bilans obejmuje cały plan od jego początku", async () => {
    const today = { ...STATE.today, period: "plan_run", plan_date: "2026-10-19", until: "2026-10-20T06:00:00+02:00" };
    mockApi({ states: [{ ...STATE, clock: { ...STATE.clock, sim_time: "2026-10-20T06:00:00+02:00" }, today }] });
    renderPage();

    const summary = await screen.findByRole("region", { name: "Podsumowanie domu" });
    expect(within(summary).getByRole("heading", { name: "Przebieg planu na 19 października · cały dom" })).toBeTruthy();
    expect(summary.textContent).toContain("19 października 00:00 – 20 października 06:00");
  });

  it("domyślnie pokazuje przekrój domu z licznikiem przy wejściu", async () => {
    mockApi();
    renderPage();

    const house = await screen.findByRole("region", { name: "Dom" });
    expect(screen.getByRole("button", { name: "Dom" }).getAttribute("aria-pressed")).toBe("true");
    expect(within(house).getByRole("img", { name: "Licznik: Oddawanie do sieci 1,20 kW" })).toBeTruthy();
    // Lampa i pralka bez pomieszczenia w stanie trafiają do „Inne”.
    const other = within(house).getByRole("group", { name: "Inne" });
    expect(within(other).getByRole("button", { name: "Lampa salon: Wyłączone" })).toBeTruthy();
    expect(within(other).getByRole("button", { name: "Pralka Bosch: Gotowe" })).toBeTruthy();
    expect(screen.queryByRole("region", { name: "Urządzenia" })).toBeNull();
  });

  it("włączenie lampy z dymku w domu wysyła polecenie, a nowy stan widać w przekroju i w dymku", async () => {
    const lampOn = { ...LAMP, room: "living_room", state: "running", power_kw: 0.06 };
    mockApi({ states: [{ ...STATE, devices: [{ ...LAMP, room: "living_room" }, WASHER] }, { ...STATE, devices: [lampOn, WASHER] }] });
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({ data: { status: "accepted", state: "running" } });
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Lampa salon: Wyłączone" }));
    const popover = screen.getByRole("dialog", { name: "Lampa salon" });
    fireEvent.click(within(popover).getByRole("button", { name: "Włącz: Lampa salon" }));

    expect(post).toHaveBeenCalledWith("/home/devices/dev_lamp_01/commands", { command: "on" });
    expect(await screen.findByRole("button", { name: "Lampa salon: Pracuje, 0,06 kW" })).toBeTruthy();
    expect(within(screen.getByRole("dialog", { name: "Lampa salon" })).getByRole("button", { name: "Wyłącz: Lampa salon" })).toBeTruthy();
    expect(screen.getByRole("group", { name: "Salon, światło włączone" })).toBeTruthy();
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
