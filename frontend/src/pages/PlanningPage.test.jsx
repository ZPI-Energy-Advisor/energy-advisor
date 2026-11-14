import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import apiClient from "../api/client";
import PlanningPage from "./PlanningPage";

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
const BODY = { saved_at: null, charging_efficiency: 0.9, devices: [WASHER, EV] };
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

// GET ustawień i ostatniego planu (domyślnie bez planu).
const mockGet = (body = BODY, plan = null) =>
  vi.spyOn(apiClient, "get").mockImplementation((url) =>
    Promise.resolve({ data: url === "/planning/plans/current" ? plan : body }));

const renderPage = (body = BODY, plan = null) => {
  const get = mockGet(body, plan);
  render(
    <MemoryRouter>
      <PlanningPage />
    </MemoryRouter>,
  );
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
    render(
      <MemoryRouter>
        <PlanningPage />
      </MemoryRouter>,
    );

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
    render(
      <MemoryRouter>
        <PlanningPage />
      </MemoryRouter>,
    );
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
    expect(within(pump).getByText(/grzanie jak w piątek 6 listopada/)).toBeTruthy();
    expect(within(pump).queryByText("Kiedy może pracować")).toBeNull();
    fireEvent.change(within(pump).getByRole("combobox"), { target: { value: "2" } });
    expect(within(boiler).getByText(/ciepłą wodę liczymy dla 3 osób z profilu/)).toBeTruthy();
    fireEvent.change(within(boiler).getByLabelText("Pojemność zbiornika"), { target: { value: "150" } });
    fireEvent.click(within(boiler).getByRole("button", { name: /Dodaj godzinę/ }));
    expect(within(boiler).getByLabelText("Bojler: woda gotowa na (3)").value).toBe("12:00");

    fireEvent.click(screen.getByRole("button", { name: "Zapisz i ułóż plan" }));

    await screen.findByText("Plan na piątek 13.11");
    const [, pumpPayload, heaterPayload] = put.mock.calls[0][1].devices;
    expect(pumpPayload).toMatchObject({ device_id: "dev_hp_01", enabled: true, shift_hours: 2 });
    expect(heaterPayload.ready_times).toEqual(["06:00", "18:00", "12:00"]);
    expect(heaterPayload.tank_liters).toBe(150);
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

  it("ostrzeżenia planu są osobno, a przy taryfie ze stałą ceną jest podpowiedź", async () => {
    renderPage(
      { ...BODY, flat_tariff: true, saved_at: "2026-11-12T14:00:00Z" },
      { ...PLAN, warnings: ["Ładowarka EV: do 6:00 auto nie naładuje się do końca, zabraknie ok. 0,6 kWh."] },
    );

    const warnings = await screen.findByRole("alert");
    expect(within(warnings).getByText(/zabraknie ok\. 0,6 kWh/)).toBeTruthy();
    expect(screen.getByText(/taryfę ze stałą ceną/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Sprawdź w Analizie taryf" }).getAttribute("href")).toBe("/results");
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
