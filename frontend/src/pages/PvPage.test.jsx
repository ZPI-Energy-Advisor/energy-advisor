import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import apiClient from "../api/client";
import PvPage from "./PvPage";

const day = (date, total, extra = {}) => ({
  date,
  available: true,
  total_kwh: total,
  cloud_cover_pct: 40,
  temperature_min_c: -0.4,
  temperature_max_c: 3.2,
  basis: "weather",
  complete: true,
  ...extra,
});

const OVERVIEW = {
  installation: {
    total_kwp: 6,
    arrays: [{ kwp: 4, tilt: 35, azimuth: 0 }, { kwp: 2, tilt: 35, azimuth: -90 }],
    inverter_kw: 5,
    estimated: false,
    settlement: "net_billing",
    price_type: "RCE",
    k_factor: null,
  },
  location_label: "Wrocław",
  approximate_location: false,
  calibration: { coefficient: 0.83, source: "history", days: 30, mape: 0.04 },
  days: [day("2026-11-24", 1.8), day("2026-11-25", 2.4), { ...day("2026-11-26", null), available: false }],
  first_data_day: "2026-10-01",
  last_data_day: "2026-11-22",
  today: "2026-11-24",
  latest_day: "2026-11-26",
};

const interval = (start, extra = {}) => ({
  start,
  model_kwh: 0.2,
  actual_kwh: null,
  consumption_kwh: 0.3,
  cloud_cover_pct: 50,
  temperature_c: 2,
  ...extra,
});

const DETAIL = {
  date: "2026-11-24",
  kind: "today",
  model_kwh: 1.8,
  actual_kwh: null,
  consumption_kwh: 20.9,
  consumption_source: "typical",
  weather_source: "forecast",
  weather_fetched_at: "2026-11-24T09:20:00Z",
  basis: "weather",
  balance: {
    production_kwh: 1.8,
    consumption_kwh: 20.9,
    self_kwh: 1.5,
    export_kwh: 0.3,
    import_kwh: 19.4,
    value: { self_pln: 1.46, export_pln: 0.12, purchase_price: 0.97, export_price: 0.4, export_price_estimated: true },
  },
  typical: { days: 28, first_day: "2026-10-14", last_day: "2026-11-20", kind: "workday" },
  notes: ["Brak cen RCE z tego dnia: wartość oddania to średnia z tych samych godzin z 14 poprzednich dni."],
  interval_minutes: 15,
  intervals: [interval("2026-11-23T23:00:00Z"), interval("2026-11-24T10:00:00Z")],
};

const ACCURACY = {
  calibration: OVERVIEW.calibration,
  days: [{ date: "2026-10-13", actual_kwh: 24.3, model_kwh: 24.6 }],
  days_without_weather: 0,
};

const PAST = {
  ...DETAIL,
  date: "2026-11-23",
  kind: "past",
  weather_source: "archive",
  actual_kwh: 1.2,
  consumption_source: "devices",
  typical: null,
};

function mockApi({ overview = OVERVIEW, details = {}, dayError = null, accuracy = ACCURACY } = {}) {
  return vi.spyOn(apiClient, "get").mockImplementation((url, config) => {
    if (url === "/pv/overview") {
      return overview instanceof Error ? Promise.reject(overview) : Promise.resolve({ data: overview });
    }
    if (url === "/pv/accuracy") return Promise.resolve({ data: accuracy });
    if (url === "/pv/day") {
      if (dayError) return Promise.reject(dayError);
      const date = config.params.date;
      return Promise.resolve({ data: details[date] ?? { ...DETAIL, date } });
    }
    return Promise.reject(new Error(`Nieoczekiwane żądanie ${url}`));
  });
}

const renderPage = () => render(<MemoryRouter><PvPage /></MemoryRouter>);
const httpError = (status, detail) => Object.assign(new Error(detail), { response: { status, data: { detail } } });

describe("PvPage", () => {
  afterEach(() => vi.restoreAllMocks());

  it("pokazuje instalację, trafność i najbliższe dni", async () => {
    mockApi();
    renderPage();

    expect(await screen.findByText(/6,00 kWp \(4,00 kWp, południe, 35°; 2,00 kWp, wschód, 35°\), falownik 5,0 kW/)).toBeTruthy();
    expect(screen.getByText(/net-billing, oddanie po RCE · Wrocław/)).toBeTruthy();
    expect(screen.getByText(/myli średnio o 4%/)).toBeTruthy();
    const cards = within(screen.getByRole("region", { name: "Najbliższe dni" })).getAllByRole("button");
    expect(cards).toHaveLength(3);
    expect(within(cards[0]).getByText(/Dziś/)).toBeTruthy();
    expect(within(cards[0]).getByText("1,8")).toBeTruthy();
    expect(within(cards[0]).getByText(/od 0 do 3°C/)).toBeTruthy();
    expect(within(cards[0]).getByText(/zachmurzenie w dzień 40%/)).toBeTruthy();
    expect(within(cards[0]).queryByText(/Najwięcej/)).toBeNull();
    expect(within(cards[2]).getByText("Brak prognozy pogody.")).toBeTruthy();
  });

  it("dla dnia bez odczytów pokazuje bilans ze szacowanym zużyciem i mówi, skąd ono jest", async () => {
    mockApi();
    renderPage();

    const section = await screen.findByRole("region", { name: /Dziś, wtorek, 24 listopada/ });
    expect(await within(section).findByText("Zużyte od razu")).toBeTruthy();
    expect(within(section).getByText("1,5 kWh")).toBeTruthy();
    expect(within(section).getByText("83% produkcji")).toBeTruthy();
    expect(within(section).getByText("1,58 zł")).toBeTruthy();
    expect(within(section).getByText(/1,46 zł mniej za prąd \+ 0,12 zł do depozytu/)).toBeTruthy();
    expect(within(section).getByText("Zużycie domu (szacunek)")).toBeTruthy();
    expect(within(section).getByText("szacunek: średnia z 28 dni roboczych z plików (14.10–20.11)")).toBeTruthy();
    expect(within(section).getByText(/Liczymy w godzinach, jak operator/)).toBeTruthy();
    expect(within(section).queryByText(/pralkę/)).toBeNull();
    expect(within(section).getByText(/\(szacunek z ostatnich dni\)/)).toBeTruthy();
  });

  it("przełącza dzień kartą i strzałkami, także w przeszłość", async () => {
    const get = mockApi({ details: { "2026-11-23": PAST } });
    renderPage();

    const cards = await screen.findAllByRole("button", { name: /Jutro/ });
    fireEvent.click(cards[0]);
    await waitFor(() => expect(get).toHaveBeenCalledWith("/pv/day", { params: { date: "2026-11-25" } }));

    fireEvent.click(screen.getByRole("button", { name: "Poprzedni dzień" }));
    fireEvent.click(screen.getByRole("button", { name: "Poprzedni dzień" }));
    expect(await screen.findByText("pogoda z archiwum")).toBeTruthy();
    expect(screen.getByText("model: 1,8 kWh")).toBeTruthy();
    expect(screen.getByText("z pliku urządzeń")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Następny dzień" }).disabled).toBe(false);
    const dayCalls = get.mock.calls.filter(([url]) => url === "/pv/day").map(([, config]) => config.params.date);
    expect(dayCalls).toEqual(["2026-11-24", "2026-11-25", "2026-11-23"]);
  });

  it("miniony dzień bez odczytów nie ma zmyślonego zużycia", async () => {
    const empty = { ...PAST, actual_kwh: null, consumption_kwh: null, consumption_source: null, balance: null,
      intervals: [interval("2026-11-23T10:00:00Z", { consumption_kwh: null })] };
    mockApi({ details: { "2026-11-23": empty } });
    renderPage();

    await screen.findAllByRole("button", { name: /Jutro/ });
    fireEvent.click(screen.getByRole("button", { name: "Poprzedni dzień" }));

    expect(await screen.findByText(/nie ma odczytów z tego dnia \(pliki obejmują 01.10.2026 – 22.11.2026\)/)).toBeTruthy();
    expect(screen.getByText("Produkcja z modelu")).toBeTruthy();
    expect(screen.queryByText("Zużyte od razu")).toBeNull();
  });

  it("trafność mówi, że pogoda z archiwum jeszcze się pobiera", async () => {
    mockApi({ accuracy: { ...ACCURACY, days: [], days_without_weather: 120 } });
    renderPage();

    expect(await screen.findByText(/Pobieramy pogodę z archiwum dla 120 dni/)).toBeTruthy();
  });

  it("bez instalacji PV kieruje do profilu", async () => {
    mockApi({ overview: httpError(404, "Profil nie ma instalacji PV.") });
    renderPage();

    expect(await screen.findByText("Profil nie ma instalacji fotowoltaicznej.")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Przejdź do profilu" }).getAttribute("href")).toBe("/profile");
  });

  it("bez połączenia z serwerem pozwala spróbować ponownie", async () => {
    const get = mockApi({ overview: new Error("Network Error") });
    renderPage();

    expect(await screen.findByText("Nie udało się połączyć z serwerem.")).toBeTruthy();
    get.mockRestore();
    mockApi();
    fireEvent.click(screen.getByRole("button", { name: "Spróbuj ponownie" }));

    expect(await screen.findByText(/myli średnio o 4%/)).toBeTruthy();
  });

  it("brak danych dnia pokazuje komunikat zamiast wykresu", async () => {
    mockApi({ dayError: httpError(503, "Nie ma pogody ani produkcji z pliku na ten dzień.") });
    renderPage();

    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.getByRole("alert").textContent).toMatch(/Nie ma pogody ani produkcji/);
  });

  it("oddanie bez cen RCE nie jest wyceniane na zero", async () => {
    const balance = { ...DETAIL.balance, value: { ...DETAIL.balance.value, export_pln: 0, export_price: null, export_price_estimated: false } };
    mockApi({ details: { "2026-11-24": { ...DETAIL, balance } } });
    renderPage();

    expect(await screen.findByText(/oddanie bez wyceny/)).toBeTruthy();
    expect(screen.queryByText(/Oddany do sieci daje/)).toBeNull();
  });

  it("szacunkowe panele i przybliżona lokalizacja mają dopiski z linkiem do profilu", async () => {
    mockApi({
      overview: {
        ...OVERVIEW,
        installation: { ...OVERVIEW.installation, estimated: true },
        approximate_location: true,
        calibration: { coefficient: 0.8, source: "default", days: 0, mape: null },
      },
    });
    renderPage();

    expect(await screen.findByText(/Panele są szacunkowe/)).toBeTruthy();
    expect(screen.getByText(/pogoda dotyczy regionu/)).toBeTruthy();
    expect(screen.getByText(/nie jest jeszcze dopasowana/)).toBeTruthy();
  });
});
