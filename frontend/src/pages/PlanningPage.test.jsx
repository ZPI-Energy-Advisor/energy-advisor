import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import apiClient from "../api/client";
import PlanningPage from "./PlanningPage";
import { CurrentUserContext } from "../context/currentUserContext";

const WASHER = {
  device_id: "dev_wm_01",
  device_name: "Pralka Bosch",
  device_type: "washing_machine",
  device_category: "AGD",
  flexibility_mode: "shiftable",
  max_power_kw: null,
  programs: [{ program_id: "cotton_60", program_name: "Bawełna 60°C", duration_min: 120 }],
  default_windows: [{ start: "07:00", end: "22:00" }],
  is_ev: false,
  preference: {
    device_id: "dev_wm_01", enabled: false, program_id: null, windows: [{ start: "07:00", end: "22:00" }],
    energy_input: "kwh", energy_kwh: null, battery_kwh: null, current_percent: null, target_percent: null,
  },
  energy_needed_kwh: null,
};
const EV = {
  ...WASHER,
  device_id: "dev_ev_01",
  device_name: "Ładowarka EV",
  device_type: "ev_charger",
  device_category: "Pojazd elektryczny",
  flexibility_mode: "interruptible",
  max_power_kw: 3.7,
  programs: [],
  default_windows: [{ start: "18:00", end: "07:00" }],
  is_ev: true,
  preference: { ...WASHER.preference, device_id: "dev_ev_01", windows: [{ start: "18:00", end: "07:00" }] },
};
const BODY = { saved_at: null, charging_efficiency: 0.9, after_max_gap_min: 60, devices: [WASHER, EV] };
const PLAN = {
  id: "plan-1",
  plan_date: "2026-11-13",
  status: "draft",
  created_at: "2026-11-12T16:00:00+01:00",
  approved_at: null,
  horizon_start: "2026-11-13T00:00:00+01:00",
  horizon_end: "2026-11-14T06:00:00+01:00",
  pricing: "PGE, G11",
  max_grid_kw: null,
  approximate_from: null,
  cost_before: 3.2,
  cost_after: 2.1,
  saving: 1.1,
  notes: ["Bojler: 3,6 kWh na dobę jak w czw. 05.11, po 1,8 kWh przed każdą godziną."],
  items: [{
    action_id: "dev_wm_01", device_id: "dev_wm_01", device_name: "Pralka Bosch", program_name: "Bawełna 60°C",
    kind: "program", original_start: "2026-11-13T07:00:00+01:00", original_end: "2026-11-13T09:00:00+01:00",
    start: "2026-11-13T13:00:00+01:00", end: "2026-11-13T15:00:00+01:00", energy_kwh: 1.4,
    cost_before: 1.4, cost_after: 0.3, status: "moved", reason: null, charging: null,
  }],
  prices: [{ start: "2026-11-13T00:00:00+01:00", price_pln_kwh: 0.9 }],
  water_heaters: [{
    device_id: "dev_wh_01", device_name: "Bojler", tank_liters: 120, residents: 3, hot_water_kwh: 4.8,
    ready_times: ["06:00", "18:00"], min_temp: 40, ready_temp: 55, max_temp: 75, loss_per_hour: 0.5, shortfall: 0,
    start_before: 55, start_after: 45,
    temperatures: [
      { start: "2026-11-13T00:00:00+01:00", before: 54.9, after: 60.2 },
      { start: "2026-11-13T00:15:00+01:00", before: 54.8, after: 65.4 },
    ],
  }],
};

const HEAT_PUMP_PLAN = {
  device_id: "dev_hp_01", device_name: "Pompa ciepła",
  plan_temperature: { mean_c: -2.2, min_c: -5.6, max_c: 1.2, source: "forecast" },
  reference_day: "2026-11-06",
  reference_temperature: { mean_c: 9.1, min_c: 5, max_c: 12, source: "archive" },
  reference_kwh: 11.2, target_kwh: 21.4, kwh: 21.4, heat_kwh: 61.8, hot_water_heat_kwh: 5.8, hdd: 20.2, cop: 2.83,
  model: { source: "history", heat_per_hdd: 2.77, hot_water_kwh: 5.6, floor_heating: true, days: 120, heating_days: 90, mape: 0.07 },
};

const INDOOR_POINTS = [{ start: "2026-11-13T00:00:00+01:00", before: 21, after: 20.8, outdoor: -2 }];

// Odpowiedź GET po adresie; adres spoza listy to ustawienia.
const routed = (url, config, responses, fallback) => (url in responses ? responses[url] : fallback);

// GET ustawień i ostatniego planu (domyślnie bez planu).
const mockGet = (body = BODY, plan = null) =>
  vi.spyOn(apiClient, "get").mockImplementation((url) =>
    Promise.resolve({ data: url === "/planning/plans/current" ? plan : body }));

// `me.home_owner`: konto z domem Smart Home może uruchomić zatwierdzony plan w symulacji.
const page = (me = { home_owner: false }) => (
  <CurrentUserContext.Provider value={{ me, isReady: true, loadError: null }}>
    <MemoryRouter initialEntries={["/plan"]}>
      <Routes>
        <Route path="/plan" element={<PlanningPage />} />
        <Route path="/home" element={<p>Mój dom</p>} />
      </Routes>
    </MemoryRouter>
  </CurrentUserContext.Provider>
);

const renderPage = (body = BODY, plan = null, me = undefined) => {
  const get = mockGet(body, plan);
  render(page(me));
  return get;
};

const card = (name) => screen.findByRole("region", { name });

// „Dziś” to 12.11, więc plan na 13.11 jest planem na jutro.
beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-11-12T15:00:00"));
});
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("PlanningPage", () => {
  it("pobiera ustawienia zalogowanego użytkownika, bez domu Smart Home", async () => {
    const get = renderPage();

    await card("Pralka Bosch");
    expect(get).toHaveBeenCalledWith("/planning/preferences");
  });

  it("przy ładowarce pojemność baterii jest tylko przy poziomie baterii, a przedziały to czas podłączenia", async () => {
    renderPage();
    const ev = await card("Ładowarka EV");
    fireEvent.click(within(ev).getByRole("checkbox", { name: "Pracuje jutro" }));

    expect(within(ev).getByText("Kiedy auto jest podłączone")).toBeTruthy();
    expect(within(ev).queryByLabelText("Pojemność baterii")).toBeNull();
    fireEvent.click(within(ev).getByRole("radio", { name: "poziom baterii" }));
    expect(within(ev).getByLabelText("Pojemność baterii")).toBeTruthy();
  });

  it("pokazuje datę ostatniego zapisu", async () => {
    mockGet({ ...BODY, saved_at: "2026-11-12T09:30:00Z" });
    render(page());

    expect(await screen.findByText(/^Ostatnio zapisano: 12\.11/)).toBeTruthy();
  });

  it("domyślne przedziały pochodzą z pliku, a urządzenie może mieć kilka przedziałów", async () => {
    renderPage();
    const washer = await card("Pralka Bosch");
    fireEvent.click(within(washer).getByRole("checkbox", { name: "Pracuje jutro" }));

    expect(within(washer).getByRole("combobox").value).toBe("cotton_60");  // pierwszy program od razu
    expect(within(washer).getByLabelText("Pralka Bosch: od (przedział 1)").value).toBe("07:00");
    expect(within(washer).getByText("Godziny co 15 minut, np. 08:00, 08:15, 08:30.")).toBeTruthy();
    expect(within(washer).queryByRole("button", { name: /Przywróć z pliku/ })).toBeNull();
    fireEvent.click(within(washer).getByRole("button", { name: /Dodaj przedział/ }));
    // Nowy przedział zaczyna się tam, gdzie kończy się ostatni.
    expect(within(washer).getByLabelText("Pralka Bosch: od (przedział 2)").value).toBe("22:00");
    expect(within(washer).getByLabelText("Pralka Bosch: do (przedział 2)").value).toBe("00:00");
    expect(within(washer).getByRole("button", { name: /Przywróć z pliku \(07:00–22:00\)/ })).toBeTruthy();
    fireEvent.click(within(washer).getByRole("button", { name: "Usuń przedział 2: Pralka Bosch" }));
    expect(within(washer).queryByLabelText("Pralka Bosch: od (przedział 2)")).toBeNull();
  });

  it("blokuje zapis, gdy przedział jest krótszy niż program", async () => {
    renderPage();
    const put = vi.spyOn(apiClient, "put");
    const washer = await card("Pralka Bosch");
    fireEvent.click(within(washer).getByRole("checkbox", { name: "Pracuje jutro" }));
    fireEvent.change(within(washer).getByLabelText("Pralka Bosch: do (przedział 1)"), { target: { value: "08:00" } });

    fireEvent.click(screen.getByRole("button", { name: "Zapisz i ułóż plan" }));

    expect(put).not.toHaveBeenCalled();
    expect(within(washer).getByText("Najdłuższy przedział (1 h) jest krótszy niż program Bawełna 60°C (2 h).")).toBeTruthy();
  });

  it("zapisuje ustawienia z poziomem baterii auta i pokazuje ułożony plan", async () => {
    renderPage();
    const put = vi.spyOn(apiClient, "put").mockResolvedValue({ data: { ...BODY, saved_at: "2026-11-12T10:00:00Z" } });
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({ data: PLAN });
    const ev = await card("Ładowarka EV");
    fireEvent.click(within(ev).getByRole("checkbox", { name: "Pracuje jutro" }));
    fireEvent.click(within(ev).getByRole("radio", { name: "poziom baterii" }));
    fireEvent.change(within(ev).getByLabelText("Pojemność baterii"), { target: { value: "60" } });
    fireEvent.change(within(ev).getByLabelText("Teraz w baterii"), { target: { value: "40" } });
    fireEvent.change(within(ev).getByLabelText("Naładuj do"), { target: { value: "70" } });
    expect(within(ev).getByText(/Z sieci auto pobierze ok\. 20,0 kWh/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Zapisz i ułóż plan" }));

    expect(await screen.findByRole("heading", { name: "Plan na piątek 13.11" })).toBeTruthy();
    expect(post).toHaveBeenCalledWith("/planning/plans", {});
    expect(put.mock.calls[0][0]).toBe("/planning/preferences");
    const body = put.mock.calls[0][1];
    expect(body).not.toHaveProperty("mode");
    expect(body.devices[1]).toMatchObject({
      device_id: "dev_ev_01", enabled: true, energy_input: "percent", battery_kwh: 60, current_percent: 40, target_percent: 70,
      windows: [{ start: "18:00", end: "07:00" }],
    });
  });

  it("suszarka po pralce ma tylko godzinę końca, a pralka nie może wtedy czekać na suszarkę", async () => {
    const dryer = {
      ...WASHER,
      device_id: "dev_td_01",
      device_name: "Suszarka",
      device_type: "tumble_dryer",
      programs: [{ program_id: "dry", program_name: "Suszenie", duration_min: 90 }],
      preference: { ...WASHER.preference, device_id: "dev_td_01" },
    };
    mockGet({ ...BODY, devices: [WASHER, dryer, EV] });
    vi.spyOn(apiClient, "post").mockResolvedValue({ data: PLAN });
    const put = vi.spyOn(apiClient, "put").mockResolvedValue({ data: { ...BODY, devices: [WASHER, dryer, EV] } });
    render(page());
    const dryerCard = await card("Suszarka");
    fireEvent.click(within(dryerCard).getByRole("checkbox", { name: "Pracuje jutro" }));
    const after = within(dryerCard).getAllByRole("combobox")[1];
    // Ładowarka nie ma programu, więc nie ma jej na liście.
    expect([...after.options].map((option) => option.textContent)).toEqual(["Nie czeka na inne urządzenie", "Pralka Bosch"]);
    fireEvent.change(after, { target: { value: "dev_wm_01" } });
    expect(within(dryerCard).getByText("Ruszy po końcu: Pralka Bosch, najwyżej 1 h później.")).toBeTruthy();
    // Start wyznacza pralka: zamiast przedziałów jest tylko „Skończ najpóźniej o”.
    expect(within(dryerCard).queryByText("Kiedy może pracować")).toBeNull();
    fireEvent.change(within(dryerCard).getByLabelText(/Skończ najpóźniej o/), { target: { value: "22:00" } });

    fireEvent.click(screen.getByRole("button", { name: "Zapisz i ułóż plan" }));
    expect(put).not.toHaveBeenCalled();
    expect(within(dryerCard).getByText("Pralka Bosch nie pracuje jutro. Zaznacz je albo usuń „Wykonaj po”.")).toBeTruthy();

    const washer = await card("Pralka Bosch");
    fireEvent.click(within(washer).getByRole("checkbox", { name: "Pracuje jutro" }));
    // Pralka nie dostaje wyboru „Wykonaj po”, bo jedyne inne urządzenie z programem już na nią czeka.
    expect(within(washer).getAllByRole("combobox")).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Zapisz i ułóż plan" }));

    expect(await screen.findByText("Plan na piątek 13.11")).toBeTruthy();
    expect(put.mock.calls[0][1].devices[1]).toMatchObject({ device_id: "dev_td_01", after_device_id: "dev_wm_01", finish_by: "22:00" });
    expect(put.mock.calls[0][1].devices[0].after_device_id).toBeNull();
  });

  it("pokazuje błąd backendu przy właściwym urządzeniu", async () => {
    renderPage();
    vi.spyOn(apiClient, "put").mockRejectedValue({ response: { status: 422, data: { detail: [
      { loc: ["body", "devices", 0, "windows"], msg: "Przedziały godzin nachodzą na siebie.", type: "value_error" },
    ] } } });
    const washer = await card("Pralka Bosch");
    fireEvent.click(within(washer).getByRole("checkbox", { name: "Pracuje jutro" }));

    fireEvent.click(screen.getByRole("button", { name: "Zapisz i ułóż plan" }));

    expect(await within(washer).findByText("Przedziały godzin nachodzą na siebie.")).toBeTruthy();
  });

  it("plan z pompą ciepła zaczyna od wniosku, a szczegóły chowa pod „Jak to liczymy”", async () => {
    renderPage({ ...BODY, saved_at: "2026-11-12T14:00:00Z" }, { ...PLAN, heat_pumps: [HEAT_PUMP_PLAN] });

    const heating = await screen.findByRole("region", { name: "Ogrzewanie: Pompa ciepła" });
    expect(within(heating).getByText(
      "W piątek 13 listopada zimniej (-2°C zamiast 9°C w piątek 6 listopada), więc pompa zużyje ok. 21,4 kWh prądu, o 10,2 kWh więcej.",
    )).toBeTruthy();
    expect(within(heating).getByText("Jak to liczymy")).toBeTruthy();
    expect(within(heating).getByText(/Prognoza na ten dzień: średnio -2°C \(od -6 do 1°C\)/)).toBeTruthy();
    expect(within(heating).getByText(/W piątek 6 listopada, z którego bierzemy godziny grzania, było średnio 9°C/)).toBeTruthy();
    expect(within(heating).getByText("62 kWh")).toBeTruthy();
    expect(within(heating).getByText("20,2 stopniodni")).toBeTruthy();
    expect(within(heating).getByText("2,8")).toBeTruthy();
    expect(within(heating).getByText("ogrzewanie podłogowe")).toBeTruthy();
    expect(within(heating).getByText("21,4 kWh")).toBeTruthy();
    expect(within(heating).getByText("wtedy 11,2 kWh")).toBeTruthy();
    expect(within(heating).getByText(/Dopasowane do zużycia pompy z Twoich plików \(120 dni, w tym 90 z ogrzewaniem\)/)).toBeTruthy();
    expect(within(heating).getByText(/myli średnio o 7%/)).toBeTruthy();
    expect(within(heating).queryByText(/zmieści się/)).toBeNull();
    expect(within(heating).queryByText(/słabo zależy od temperatury/)).toBeNull();
  });

  it("plan pilnujący temperatury w domu: zakres, prąd, stygnięcie i wykres temperatury", async () => {
    const temperatures = Array.from({ length: 96 }, (_, index) => ({
      start: new Date(Date.UTC(2026, 10, 12, 23) + index * 900000).toISOString(),
      before: 21, after: 20.5 + (index % 8) / 8, outdoor: -2,
    }));
    const pump = {
      ...HEAT_PUMP_PLAN, mode: "indoor", reference_temperature: null, reference_kwh: null, kwh: 18.3,
      band: [20, 22], shortfall: 0, thermostat_kwh: 17.1, cooling_per_hour: 0.45, time_constant_h: 43, temperatures,
      cost_pln: 9.85, thermostat_cost_pln: 12.4, hot_water_heat_kwh: 0,
    };
    renderPage({ ...BODY, saved_at: "2026-11-12T14:00:00Z" }, { ...PLAN, heat_pumps: [pump] });

    const heating = await screen.findByRole("region", { name: "Ogrzewanie: Pompa ciepła" });
    expect(within(heating).getByText(
      "W piątek 13 listopada średnio -2°C. Plan trzyma w domu 20–22°C i zużyje ok. 18,3 kWh prądu, grzejąc głównie w tańszych godzinach.",
    )).toBeTruthy();
    expect(within(heating).getByText(/dom stygnie przy tej pogodzie o ok. 0,5°C na godzinę/)).toBeTruthy();
    expect(within(heating).getByText("Koszt ogrzewania")).toBeTruthy();
    expect(within(heating).getByText(/ze stałą temperaturą 12,40 zł/)).toBeTruthy();
    // Bez bojlera w planie i z pompą, która nie grzeje wody: bez kafelka z zerem.
    expect(within(heating).queryByText("Z tego ciepła woda")).toBeNull();
    // Wykres temperatury w domu jest w okienku, jak temperatura wody.
    fireEvent.click(screen.getByRole("button", { name: "Temperatura w domu" }));
    const dialog = await screen.findByRole("dialog", { name: "Temperatura w domu: Pompa ciepła" });
    expect(within(dialog).getByText("w domu według planu")).toBeTruthy();
  });

  it("przyciski planu są w jednej grupie, a przy dwóch bojlerach i dwóch pompach mają nazwy urządzeń", async () => {
    const indoor = { ...HEAT_PUMP_PLAN, mode: "indoor", band: [20, 22], shortfall: 0, temperatures: INDOOR_POINTS };
    const heaters = [PLAN.water_heaters[0], { ...PLAN.water_heaters[0], device_id: "dev_wh_02", device_name: "Bojler łazienka" }];
    const pumps = [indoor, { ...indoor, device_id: "dev_hp_02", device_name: "Pompa garaż" }];
    renderPage({ ...BODY, saved_at: "2026-11-12T14:00:00Z" }, { ...PLAN, water_heaters: heaters, heat_pumps: pumps });

    const group = await screen.findByRole("group", { name: "Ustawienia planu" });
    expect(within(group).getAllByRole("button").map((button) => button.textContent.trim())).toEqual([
      "Edytuj ustawienia", "Temperatura wody: Bojler", "Temperatura wody: Bojler łazienka",
      "Temperatura w domu: Pompa ciepła", "Temperatura w domu: Pompa garaż",
    ]);
    fireEvent.click(within(group).getByRole("button", { name: "Temperatura w domu: Pompa garaż" }));
    expect(await screen.findByRole("dialog", { name: "Temperatura w domu: Pompa garaż" })).toBeTruthy();
  });

  it("przy jednym bojlerze i jednej pompie przyciski mają krótkie nazwy", async () => {
    const indoor = { ...HEAT_PUMP_PLAN, mode: "indoor", band: [20, 22], shortfall: 0, temperatures: INDOOR_POINTS };
    renderPage({ ...BODY, saved_at: "2026-11-12T14:00:00Z" }, { ...PLAN, heat_pumps: [indoor] });

    const group = await screen.findByRole("group", { name: "Ustawienia planu" });
    expect(within(group).getAllByRole("button").map((button) => button.textContent.trim())).toEqual([
      "Edytuj ustawienia", "Temperatura wody", "Temperatura w domu",
    ]);
  });

  it("pompa ostrzega o chłodzie tylko z powodem: za mała moc albo limit przyłącza", async () => {
    const indoor = { ...HEAT_PUMP_PLAN, mode: "indoor", band: [20, 22], temperatures: [] };
    const pumps = [
      { ...indoor, shortfall: 1.2, shortfall_reason: "power" },
      { ...indoor, device_id: "dev_hp_02", device_name: "Pompa garaż", shortfall: 0.8, shortfall_reason: "grid" },
      { ...indoor, device_id: "dev_hp_03", device_name: "Pompa trzecia", shortfall: 0.2, shortfall_reason: null },
      { ...indoor, device_id: "dev_hp_04", device_name: "Pompa sprzed zmiany", shortfall: 0.9 },
    ];
    renderPage({ ...BODY, saved_at: "2026-11-12T14:00:00Z" }, { ...PLAN, heat_pumps: pumps });

    const first = await screen.findByRole("region", { name: "Ogrzewanie: Pompa ciepła" });
    expect(within(first).getByText(/Przy tej pogodzie pompa nie utrzyma w domu 20°C \(zabraknie ok. 1,2°C\)/)).toBeTruthy();
    const second = screen.getByRole("region", { name: "Ogrzewanie: Pompa garaż" });
    expect(within(second).getByText(/Limit mocy przyłącza nie zostawia pompie miejsca/)).toBeTruthy();
    const third = screen.getByRole("region", { name: "Ogrzewanie: Pompa trzecia" });
    expect(within(third).queryByText(/W domu może być chłodniej/)).toBeNull();
    const older = screen.getByRole("region", { name: "Ogrzewanie: Pompa sprzed zmiany" });
    expect(within(older).getByText(/Przy tej pogodzie pompa nie utrzyma w domu 20°C/)).toBeTruthy();
  });

  it("karta pompy: temperatura w domu, ciepła woda osobno, archiwum i słabe dopasowanie", async () => {
    const pump = {
      ...HEAT_PUMP_PLAN,
      plan_temperature: { mean_c: 3, min_c: 3.2, max_c: 2.8, source: "archive" },
      indoor_c: 23,
      water: { ready_times: ["06:30", "19:00"], tank_liters: 200, kwh: 2.25, cop: 2.4, shortfall: 0 },
      model: { ...HEAT_PUMP_PLAN.model, mape: 0.26 },
    };
    renderPage({ ...BODY, saved_at: "2026-11-12T14:00:00Z" }, { ...PLAN, heat_pumps: [pump] });

    const heating = await screen.findByRole("region", { name: "Ogrzewanie: Pompa ciepła" });
    expect(within(heating).getByText(/zużyje ok. 21,4 kWh prądu przy 23°C w domu/)).toBeTruthy();
    expect(within(heating).getByText(/Ciepła woda w zasobniku 200 l będzie gotowa na 06:30 i 19:00/)).toBeTruthy();
    // Plan na dzień z przeszłości: pogoda z archiwum, a zakres bez powtórzenia, gdy min i max są równe.
    expect(within(heating).getByText(/^Pogoda z archiwum: średnio 3°C\. /)).toBeTruthy();
    expect(within(heating).getByText(/słabo zależy od temperatury \(dobowe zużycie myli średnio o 26%\)/)).toBeTruthy();
  });

  it("plan z PV pokazuje prognozę, na ile liczy i bilans paneli bez planu i według planu", async () => {
    const pv = {
      forecast_kwh: 14.2, planned_kwh: 12.5, uncertainty: 0.12, uncertainty_source: "history", basis: "weather",
      weather_fetched_at: "2026-11-12T14:20:00Z", coefficient: 0.83, settlement: "net_billing",
      export_estimated: true, export_unpriced: false,
      before: { self_kwh: 4.1, export_kwh: 8.4, import_kwh: 20.2, plan_from_pv_kwh: 0.3, export_pln: 2.52 },
      after: { self_kwh: 6.0, export_kwh: 6.5, import_kwh: 18.3, plan_from_pv_kwh: 2.2, export_pln: 1.95 },
    };
    renderPage({ ...BODY, saved_at: "2026-11-12T14:00:00Z" }, { ...PLAN, pv });

    const card = await screen.findByRole("region", { name: "Prąd z paneli" });
    expect(within(card).getByText(/Prognoza 14,2 kWh, plan liczy na 12,5 kWh \(o 12% mniej/)).toBeTruthy();
    const row = within(card).getByText("Urządzenia z planu biorą z paneli").closest("tr");
    expect(within(row).getByText("0,3 kWh")).toBeTruthy();
    expect(within(row).getByText("2,2 kWh")).toBeTruthy();
    const value = within(card).getByText("Wartość oddania do depozytu").closest("tr");
    expect(within(value).getByText("2,52 zł")).toBeTruthy();
    expect(within(value).getByText("1,95 zł")).toBeTruthy();
    expect(within(card).getByText(/wartość oddania to średnia z ostatnich dni/)).toBeTruthy();
    expect(within(card).queryByText(/prąd oddany do sieci jest wart więcej/)).toBeNull();
  });

  it("plan idealny: karta paneli mówi o pogodzie z archiwum, a przy drogim oddaniu wyjaśnia, czemu nie przesuwa", async () => {
    const pv = {
      forecast_kwh: 3.2, planned_kwh: 3.2, uncertainty: 0, uncertainty_source: "archive", basis: "weather",
      weather_fetched_at: null, coefficient: 0.83, settlement: "net_billing", export_estimated: false,
      export_unpriced: false, export_beats_grid: true, hours: [],
    };
    renderPage({ ...BODY, saved_at: "2026-11-12T14:00:00Z" }, { ...PLAN, pv });

    const card = await screen.findByRole("region", { name: "Prąd z paneli" });
    expect(within(card).getByText(/Z pogody z archiwum 3,2 kWh. To pogoda, która naprawdę była/)).toBeTruthy();
    expect(within(card).queryByText(/o 0% mniej/)).toBeNull();
    expect(within(card).getByText(/prąd oddany do sieci jest wart więcej niż prąd z sieci/)).toBeTruthy();
  });

  it("oś doby ma pogodę i prąd z paneli z migawki planu, nadwyżkę i pralkę z paneli", async () => {
    const quarters = Array.from({ length: 96 }, (_, index) => {
      const hour = Math.floor(index / 4);
      const minute = String((index % 4) * 15).padStart(2, "0");
      return {
        start: `2026-11-13T${String(hour).padStart(2, "0")}:${minute}:00+01:00`,
        temperature_c: hour < 12 ? 2 : 8, cloud_cover_pct: hour < 12 ? 90 : 10,
      };
    });
    const hours = [11, 12, 13].map((hour) => ({
      start: `2026-11-13T${hour}:00:00+01:00`, forecast_kwh: 1.5, planned_kwh: 1.2, rest_kwh: 0.3,
      surplus_kwh: hour === 11 ? 0.02 : 0.9, plan_kwh: hour === 13 ? 0.7 : 0, export_kwh: 0.2,
    }));
    const pv = {
      forecast_kwh: 4.5, planned_kwh: 3.6, uncertainty: 0.2, uncertainty_source: "default", basis: "weather",
      weather_fetched_at: "2026-11-12T15:20:00+01:00", coefficient: 1, settlement: "net_billing",
      export_estimated: false, export_unpriced: false, estimated_installation: true, hours,
      before: { self_kwh: 1, export_kwh: 2, import_kwh: 5, plan_from_pv_kwh: 0, export_pln: 0.5 },
      after: { self_kwh: 2, export_kwh: 1, import_kwh: 4, plan_from_pv_kwh: 1.2, export_pln: 0.3 },
    };
    const items = [{ ...PLAN.items[0], pv_kwh: 1.2 }];
    const weather = { fetched_at: "2026-11-12T15:20:00+01:00", approximate_location: true, past: false, quarters };
    renderPage({ ...BODY, saved_at: "2026-11-12T14:00:00Z" }, { ...PLAN, items, pv, weather });

    const card = await screen.findByRole("region", { name: "Prąd z paneli" });
    expect(within(card).getByText("Prognoza pogody pobrana 12.11 15:20.")).toBeTruthy();
    expect(within(card).getByText(/Prognoza orientacyjna: panele w profilu są szacunkowe/)).toBeTruthy();
    expect(within(card).getByText(/Pogoda dla regionu/)).toBeTruthy();
    expect(within(card).getAllByRole("link").map((link) => link.getAttribute("href"))).toEqual(["/profile", "/profile"]);

    const clouds = screen.getAllByLabelText("Zachmurzenie co godzinę")[0];
    expect(clouds.children).toHaveLength(24);
    expect(clouds.children[0].getAttribute("title")).toBe("00:00: pochmurno, 2°C");
    expect(clouds.children[12].getAttribute("title")).toBe("12:00: bezchmurnie, 8°C");
    expect(within(screen.getByLabelText("Temperatura co godzinę")).getAllByText(/°$/)).toHaveLength(8);
    const panels = screen.getByLabelText("Prąd z paneli co godzinę");
    expect(panels.children).toHaveLength(3);
    expect(panels.querySelectorAll("[data-surplus]")).toHaveLength(2);
    expect(panels.children[1].getAttribute("title")).toBe("12:00: plan liczy na 1,2 kWh z paneli, nadwyżka nad resztą domu 0,9 kWh");
    expect(screen.getByText("nadwyżka z paneli")).toBeTruthy();
    expect(screen.getByText("1,2 z 1,4 kWh z paneli")).toBeTruthy();
  });

  it("plan bez prognozy PV mówi to na osi zamiast pustego pasa", async () => {
    renderPage({ ...BODY, saved_at: "2026-11-12T14:00:00Z" }, { ...PLAN, pv: null, pv_reason: "no_weather", weather: null });

    expect(await screen.findByRole("note")).toHaveProperty(
      "textContent", "Nie ma prognozy pogody na ten dzień, więc plan liczy się bez paneli.",
    );
    expect(screen.queryByLabelText("Prąd z paneli co godzinę")).toBeNull();
    expect(screen.queryByLabelText("Zachmurzenie co godzinę")).toBeNull();
  });

  it("dom bez paneli nie ma pasa paneli, a pogoda zostaje", async () => {
    const weather = {
      fetched_at: null, approximate_location: false, past: true,
      quarters: [{ start: "2026-11-13T10:00:00+01:00", temperature_c: 3, cloud_cover_pct: 50 }],
    };
    renderPage({ ...BODY, saved_at: "2026-11-12T14:00:00Z" }, { ...PLAN, pv: null, pv_reason: "no_installation", weather });

    await screen.findByText("Szkic");
    expect(screen.queryByText(/Z paneli/)).toBeNull();
    expect(screen.getAllByLabelText("Zachmurzenie co godzinę")[0].children).toHaveLength(1);
  });

  it("pompa z modelem z profilu i za małą mocą mówi o tym wprost", async () => {
    const pump = {
      ...HEAT_PUMP_PLAN, kwh: 30, target_kwh: 41.5,
      model: { ...HEAT_PUMP_PLAN.model, source: "building", days: 0, heating_days: 0, mape: null, floor_heating: false },
    };
    renderPage({ ...BODY, saved_at: "2026-11-12T14:00:00Z" }, { ...PLAN, heat_pumps: [pump] });

    const heating = await screen.findByRole("region", { name: "Ogrzewanie: Pompa ciepła" });
    expect(within(heating).getByText("grzejniki")).toBeTruthy();
    expect(within(heating).getByText(/ok. 41,5 kWh prądu pompy, ale przy jej mocy zmieści się 30,0 kWh/)).toBeTruthy();
    expect(within(heating).getByText(/Liczone z profilu \(rok budowy i metraż\)/)).toBeTruthy();
  });

  it("od razu pokazuje plan ułożony po ostatnim zapisie i pozwala go zatwierdzić", async () => {
    renderPage({ ...BODY, saved_at: "2026-11-12T14:00:00Z" }, PLAN);
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({
      data: { ...PLAN, status: "approved", approved_at: "2026-11-12T16:05:00+01:00" },
    });

    expect(await screen.findByText("Szkic")).toBeTruthy();
    expect(screen.getByText("Oszczędność")).toBeTruthy();
    expect(screen.getByText("1,10 zł")).toBeTruthy();
    expect(screen.getByText("34,4%")).toBeTruthy(); // 1,10 z 3,20 zł
    expect(screen.getByText("13.11 07:00–09:00")).toBeTruthy();
    expect(screen.getByText(PLAN.notes[0])).toBeTruthy();
    // Wykres temperatury wody otwiera się w okienku.
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Temperatura wody/ }));
    const dialog = screen.getByRole("dialog", { name: "Temperatura wody: Bojler" });
    expect(within(dialog).getByText(/Woda jest gorąca na 06:00 i 18:00/)).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Zamknij" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Zatwierdź plan" }));

    expect(await screen.findByText(/Plan zatwierdzony o 16:05/)).toBeTruthy();
    expect(post).toHaveBeenCalledWith("/planning/plans/plan-1/approve");
    expect(screen.getByText("Zatwierdzony")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Edytuj ustawienia/ }));
    expect(await card("Pralka Bosch")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Wróć do planu bez zmian" }));
    expect(screen.getByText("Zatwierdzony")).toBeTruthy();
  });

  it("właściciel domu uruchamia zatwierdzony plan w symulacji i przechodzi do „Mój dom”", async () => {
    const approved = { ...PLAN, status: "approved", approved_at: "2026-11-12T16:05:00+01:00" };
    renderPage({ ...BODY, saved_at: "2026-11-12T14:00:00Z" }, approved, { home_owner: true });
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({ data: { id: "run-1", status: "running" } });

    fireEvent.click(await screen.findByRole("button", { name: "Uruchom symulację" }));

    expect(await screen.findByText("Mój dom")).toBeTruthy();
    expect(post).toHaveBeenCalledWith("/home/plan-runs", { plan_id: "plan-1" });
  });

  it("pokazuje powód, gdy planu nie da się uruchomić, i zostaje przy planie", async () => {
    const approved = { ...PLAN, status: "approved", approved_at: "2026-11-12T16:05:00+01:00" };
    renderPage({ ...BODY, saved_at: "2026-11-12T14:00:00Z" }, approved, { home_owner: true });
    const detail = "Ten plan ułożono, zanim można było go uruchomić w symulacji. Ułóż go ponownie i zatwierdź.";
    vi.spyOn(apiClient, "post").mockRejectedValue({ response: { status: 409, data: { detail } } });

    fireEvent.click(await screen.findByRole("button", { name: "Uruchom symulację" }));

    expect((await screen.findByRole("alert")).textContent).toBe(detail);
    expect(screen.getByRole("button", { name: "Uruchom symulację" }).disabled).toBe(false);
  });

  it("bez domu Smart Home zatwierdzonego planu nie da się uruchomić w symulacji", async () => {
    const approved = { ...PLAN, status: "approved", approved_at: "2026-11-12T16:05:00+01:00" };
    renderPage({ ...BODY, saved_at: "2026-11-12T14:00:00Z" }, approved);

    expect(await screen.findByText(/Plan zatwierdzony o 16:05/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Uruchom symulację" })).toBeNull();
  });

  it("bez cen na jutro pokazuje godzinę publikacji i układa plan demo na ostatni dzień z cenami", async () => {
    renderPage();
    vi.spyOn(apiClient, "put").mockResolvedValue({ data: BODY });
    const post = vi.spyOn(apiClient, "post")
      .mockRejectedValueOnce({ response: { status: 409, data: { detail: {
        code: "no_prices", message: "Nie ma jeszcze cen dynamicznych na 13.11.2026. PSE publikuje ceny ok. 14:00.",
        latest_price_date: "2026-11-12",
      } } } })
      .mockResolvedValueOnce({ data: { ...PLAN, plan_date: "2026-11-12" } });
    const washer = await card("Pralka Bosch");
    fireEvent.click(within(washer).getByRole("checkbox", { name: "Pracuje jutro" }));

    fireEvent.click(screen.getByRole("button", { name: "Zapisz i ułóż plan" }));

    expect(await screen.findByText(/PSE publikuje ceny ok\. 14:00/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Ułóż plan demo na 12\.11/ }));
    expect(await screen.findByText("Plan na czwartek 12.11")).toBeTruthy();
    expect(post).toHaveBeenLastCalledWith("/planning/plans", { plan_date: "2026-11-12" });
  });

  it("pompa ciepła i bojler są w osobnej sekcji, bez przedziałów godzin", async () => {
    const heatPump = {
      ...WASHER, device_id: "dev_hp_01", device_name: "Pompa ciepła", device_type: "heat_pump", programs: [],
      kind: "heat_pump", history_kwh: 12.4, history_day: "2026-11-06",
      preference: { ...WASHER.preference, device_id: "dev_hp_01", enabled: true, shift_hours: 1, windows: [] },
    };
    const heater = {
      ...heatPump, device_id: "dev_wh_01", device_name: "Bojler", device_type: "water_heater", kind: "water_heater",
      history_kwh: null, history_day: null, residents: 3, hot_water_kwh: 4.8,
      preference: {
        ...heatPump.preference, device_id: "dev_wh_01", shift_hours: null, ready_times: ["06:00", "18:00"], tank_liters: 120,
      },
    };
    renderPage({ ...BODY, devices: [WASHER, heatPump, heater] });
    const put = vi.spyOn(apiClient, "put").mockResolvedValue({ data: BODY });
    vi.spyOn(apiClient, "post").mockResolvedValue({ data: PLAN });

    const pump = await card("Pompa ciepła");
    const boiler = await card("Bojler");
    expect(screen.getByRole("heading", { name: "Ogrzewanie i ciepła woda" })).toBeTruthy();
    expect(within(pump).getByText(/plan trzyma temperaturę w domu według prognozy pogody/)).toBeTruthy();
    expect(within(pump).queryByText("Kiedy może pracować")).toBeNull();
    expect(within(pump).queryByText(/Można przesunąć grzanie/)).toBeNull();
    expect(within(pump).getByLabelText(/Temperatura w domu/).value).toBe("21");
    fireEvent.change(within(pump).getByLabelText(/Temperatura w domu/), { target: { value: "22" } });
    // Dom ma bojler, więc pompa nie grzeje wody i nie pytamy o jej godziny.
    expect(within(pump).queryByText(/Ciepła woda z pompy/)).toBeNull();
    expect(within(boiler).getByText(/ciepłą wodę liczymy dla 3 osób z profilu/)).toBeTruthy();
    fireEvent.change(within(boiler).getByLabelText("Pojemność zbiornika"), { target: { value: "150" } });
    fireEvent.click(within(boiler).getByRole("button", { name: /Dodaj godzinę/ }));
    expect(within(boiler).getByLabelText("Bojler: woda gotowa na (3)").value).toBe("12:00");

    fireEvent.click(screen.getByRole("button", { name: "Zapisz i ułóż plan" }));

    await screen.findByText("Plan na piątek 13.11");
    const [, pumpPayload, heaterPayload] = put.mock.calls[0][1].devices;
    expect(pumpPayload).toMatchObject({ device_id: "dev_hp_01", enabled: true, shift_hours: 1, indoor_temp_c: 22 });
    expect(heaterPayload.ready_times).toEqual(["06:00", "18:00", "12:00"]);
    expect(heaterPayload.tank_liters).toBe(150);
  });

  it("w domu bez bojlera przy pompie można ustawić godziny ciepłej wody", async () => {
    const heatPump = {
      ...WASHER, device_id: "dev_hp_01", device_name: "Pompa ciepła", device_type: "heat_pump", programs: [],
      kind: "heat_pump", history_kwh: 12.4, history_day: "2026-11-06",
      preference: { ...WASHER.preference, device_id: "dev_hp_01", enabled: true, shift_hours: 1, windows: [] },
    };
    renderPage({ ...BODY, devices: [WASHER, heatPump] });
    const put = vi.spyOn(apiClient, "put").mockResolvedValue({ data: BODY });
    vi.spyOn(apiClient, "post").mockResolvedValue({ data: PLAN });

    const pump = await card("Pompa ciepła");
    expect(within(pump).getByText(/Bez godzin woda będzie gotowa na 6:00 i 18:00/)).toBeTruthy();
    fireEvent.click(within(pump).getByRole("button", { name: /Dodaj godzinę/ }));
    fireEvent.click(screen.getByRole("button", { name: "Zapisz i ułóż plan" }));

    await screen.findByText("Plan na piątek 13.11");
    const [, pumpPayload] = put.mock.calls[0][1].devices;
    expect(pumpPayload.ready_times).toHaveLength(1);
  });

  it("pojemność bojlera z pliku urządzeń jest tylko do odczytu", async () => {
    const heater = {
      ...WASHER, device_id: "dev_wh_01", device_name: "Bojler", device_type: "water_heater", programs: [],
      kind: "water_heater", residents: 2, hot_water_kwh: 3.2, tank_liters_from_file: 150,
      preference: { ...WASHER.preference, device_id: "dev_wh_01", enabled: true, ready_times: ["06:00"], tank_liters: 150 },
    };
    renderPage({ ...BODY, devices: [heater] });

    const boiler = await card("Bojler");

    expect(within(boiler).getByText("(z pliku urządzeń)")).toBeTruthy();
    expect(within(boiler).queryByLabelText("Pojemność zbiornika")).toBeNull();
  });

  it("ciepła woda bojlera z historii w plikach, gdy ją ma", async () => {
    const heater = {
      ...WASHER, device_id: "dev_wh_01", device_name: "Bojler", device_type: "water_heater", programs: [],
      kind: "water_heater", residents: 2, history_kwh: 3.6, hot_water_kwh: 2.48, hot_water_source: "history",
      preference: { ...WASHER.preference, device_id: "dev_wh_01", enabled: true, ready_times: ["06:00"], tank_liters: 80 },
    };
    renderPage({ ...BODY, devices: [heater] });

    const boiler = await card("Bojler");

    expect(within(boiler).getByText(/ile ciepłej wody zużywacie, bierzemy z historii/)).toBeTruthy();
  });

  it("plan na wcześniejszy dzień można od razu ułożyć na jutro", async () => {
    renderPage({ ...BODY, saved_at: "2026-11-11T14:00:00Z" }, { ...PLAN, plan_date: "2026-11-12" });
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({ data: PLAN });

    expect(await screen.findByText(/To plan na czwartek 12\.11, czyli nie na jutro/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Ułóż plan na jutro/ }));

    expect(await screen.findByText("Plan na piątek 13.11")).toBeTruthy();
    expect(post).toHaveBeenCalledWith("/planning/plans", {});
    expect(screen.queryByText(/czyli nie na jutro/)).toBeNull();
  });

  it("przełącznik „Wybrany dzień” pokazuje plan idealny, a „Jutro” dalej plan na jutro", async () => {
    const tomorrow = { ...PLAN, status: "approved", approved_at: "2026-11-12T16:05:00+01:00" };
    const past = { ...PLAN, id: "plan-past", plan_date: "2026-10-30", kind: "past_day", day_source: "files" };
    vi.spyOn(apiClient, "get").mockImplementation((url, config) => Promise.resolve({ data: routed(url, config, {
      "/planning/plans/current": tomorrow,
      "/planning/past-days": { first_day: "2024-08-24", last_day: "2026-11-11", file_periods: [{ first_day: "2026-10-01", last_day: "2026-10-30" }] },
      "/planning/plans": config?.params?.date === "2026-10-30" ? past : null,
    }, { ...BODY, saved_at: "2026-11-12T14:00:00Z" }) }));
    render(page());

    expect(await screen.findByRole("heading", { name: "Plan na piątek 13.11" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Wybrany dzień" }));
    expect(await screen.findByRole("heading", { name: "Plan idealny na piątek 30.10" })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Plan na piątek 13.11" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Jutro" }));
    expect(await screen.findByRole("heading", { name: "Plan na piątek 13.11" })).toBeTruthy();
    expect(screen.getByText("Zatwierdzony")).toBeTruthy();
  });

  it("plan demo na dzień z przeszłości otwiera się jako plan idealny tego dnia", async () => {
    const past = { ...PLAN, id: "plan-demo", plan_date: "2026-11-10", kind: "past_day", day_source: "settings" };
    vi.spyOn(apiClient, "get").mockImplementation((url, config) => Promise.resolve({ data: routed(url, config, {
      "/planning/plans/current": null,
      "/planning/past-days": { first_day: "2024-08-24", last_day: "2026-11-11", file_periods: [] },
      "/planning/plans": config?.params?.date === "2026-11-10" ? past : null,
    }, BODY) }));
    vi.spyOn(apiClient, "put").mockResolvedValue({ data: BODY });
    vi.spyOn(apiClient, "post")
      .mockRejectedValueOnce({ response: { status: 409, data: { detail: {
        code: "no_prices", message: "Nie ma jeszcze cen dynamicznych na 13.11.2026.", latest_price_date: "2026-11-10",
      } } } })
      .mockResolvedValueOnce({ data: past });
    render(page());

    fireEvent.click(await screen.findByRole("button", { name: "Zapisz i ułóż plan" }));
    fireEvent.click(await screen.findByRole("button", { name: /Ułóż plan demo na 10\.11/ }));

    expect(await screen.findByRole("heading", { name: "Plan idealny na wtorek 10.11" })).toBeTruthy();
    expect(screen.getByLabelText("Dzień").value).toBe("2026-11-10");
  });

  it("ostrzeżenia planu są osobno, a przy taryfie ze stałą ceną jest podpowiedź", async () => {
    renderPage(
      { ...BODY, flat_tariff: true, saved_at: "2026-11-12T14:00:00Z" },
      { ...PLAN, warnings: ["Ładowarka EV: do 6:00 auto nie naładuje się do końca, zabraknie ok. 0,6 kWh."] },
    );

    const warnings = await screen.findByRole("alert");
    expect(within(warnings).getByText(/zabraknie ok\. 0,6 kWh/)).toBeTruthy();
    expect(screen.getByText(/taryfę ze stałą ceną/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Sprawdź w Analizie taryf" }).getAttribute("href")).toBe("/tariffs");
  });

  it("przy stałej cenie i nadwyżce z paneli plan mówi, że przesuwa pod słońce", async () => {
    const summary = { self_kwh: 4, export_kwh: 3.2, import_kwh: 10, plan_from_pv_kwh: 0.2, export_pln: 1.2 };
    const pv = {
      forecast_kwh: 9, planned_kwh: 7.2, uncertainty: 0.2, uncertainty_source: "default", settlement: "net_billing",
      rest_source: "meter", before: summary, after: { ...summary, export_kwh: 1.8, plan_from_pv_kwh: 1.6 },
    };
    renderPage({ ...BODY, flat_tariff: true, saved_at: "2026-11-12T14:00:00Z" }, { ...PLAN, pv });

    expect(await screen.findByText(/plan przesuwa urządzenia tylko pod słońce/)).toBeTruthy();
    expect(screen.queryByText(/przesuwanie urządzeń prawie nie obniży rachunku/)).toBeNull();
    const card = screen.getByRole("region", { name: "Prąd z paneli" });
    expect(within(card).getByText("Jak to liczymy")).toBeTruthy();
    expect(within(card).getByText(/z licznika, bez urządzeń z planu/)).toBeTruthy();
  });

  it("bez profilu podpowiada przejście do profilu", async () => {
    renderPage();
    vi.spyOn(apiClient, "put").mockResolvedValue({ data: BODY });
    vi.spyOn(apiClient, "post").mockRejectedValue({ response: { status: 409, data: {
      detail: "Uzupełnij profil (operator i taryfa), żeby optymalizacja liczyła ceny Twojej taryfy.",
    } } });
    const washer = await card("Pralka Bosch");
    fireEvent.click(within(washer).getByRole("checkbox", { name: "Pracuje jutro" }));

    fireEvent.click(screen.getByRole("button", { name: "Zapisz i ułóż plan" }));

    expect(await screen.findByRole("link", { name: "Przejdź do profilu" })).toBeTruthy();
  });
});
