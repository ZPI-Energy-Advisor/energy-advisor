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

const mockApi = ({ connection = CONNECTED, states = [STATE] } = {}) => {
  let calls = 0;
  return vi.spyOn(apiClient, "get").mockImplementation((url) => {
    if (url === "/home") return Promise.resolve({ data: connection });
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
