import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import apiClient from "../api/client";
import DashboardPv from "./DashboardPv";

const OVERVIEW = {
  today: "2026-11-26",
  days: [
    { date: "2026-11-26", available: true, total_kwh: 5.3 },
    { date: "2026-11-27", available: true, total_kwh: 2.04 },
  ],
};
const PERIOD = {
  date_from: "2026-10-01", date_to: "2026-10-30", days: 30, model_days: 28, model_kwh: 112.44,
  actual_kwh: 98.1, export_kwh: null, estimated_installation: false, approximate_location: false,
};
const RANGE = { from: "2026-10-01", to: "2026-10-30" };
const notFound = () => Object.assign(new Error("404"), { response: { status: 404 } });

// Odpowiedzi obu zapytań karty: jutrzejsza prognoza i okres pliku.
const mockApi = ({ overview = OVERVIEW, period = PERIOD } = {}) =>
  vi.spyOn(apiClient, "get").mockImplementation((url) => {
    const data = url === "/pv/overview" ? overview : period;
    return data instanceof Error ? Promise.reject(data) : Promise.resolve({ data });
  });

const renderCard = (range = RANGE) => render(<MemoryRouter><DashboardPv range={range} /></MemoryRouter>);

describe("DashboardPv", () => {
  afterEach(() => vi.restoreAllMocks());

  it("w jednej karcie: jutro z paneli, szacunek z pogody i produkcja z pliku urządzeń", async () => {
    const get = mockApi();
    renderCard();

    const card = await screen.findByRole("region", { name: "Panele" });
    await vi.waitFor(() => expect(card.textContent).toContain("ok. 112,44 kWh"));
    expect(get).toHaveBeenCalledWith("/pv/period", { params: RANGE });
    expect(card.textContent).toContain("Jutro z paneli (prognoza)ok. 2,04 kWh");
    expect(card.textContent).toContain("Pogoda dla 28 z 30 dni z plików: obie liczby są z tych samych dni.");
    expect(card.textContent).toContain("W tym okresie: produkcja z pliku urządzeń98,10 kWh");
    expect(screen.queryByText(/szacunkowe/)).toBeNull();
  });

  it("przy pliku z licznika pokazuje oddanie i dopiski z linkiem do profilu", async () => {
    mockApi({
      period: { ...PERIOD, model_days: 30, actual_kwh: null, export_kwh: 40.2, estimated_installation: true, approximate_location: true },
    });
    renderCard();

    const card = await screen.findByRole("region", { name: "Panele" });
    await vi.waitFor(() => expect(card.textContent).toContain("W tym okresie: oddane do sieci (licznik)40,20 kWh"));
    expect(card.textContent).toContain("Szacunek orientacyjny");
    expect(card.textContent).toContain("Pogoda dla regionu");
    expect(screen.getByRole("link", { name: "Uzupełnij panele w profilu" }).getAttribute("href")).toBe("/profile");
  });

  it("bez danych z pliku pokazuje samą jutrzejszą prognozę", async () => {
    const get = mockApi();
    renderCard(null);

    const card = await screen.findByRole("region", { name: "Panele" });
    expect(card.textContent).toContain("ok. 2,04 kWh");
    expect(card.textContent).not.toContain("W tym okresie");
    expect(get).not.toHaveBeenCalledWith("/pv/period", expect.anything());
  });

  it("bez instalacji PV w profilu nic nie pokazuje", async () => {
    const get = mockApi({ overview: notFound(), period: notFound() });
    const { container } = renderCard();

    await vi.waitFor(() => expect(get).toHaveBeenCalledTimes(2));
    await Promise.resolve();
    expect(container.textContent).toBe("");
  });

  it("przy błędzie serwera mówi, że nie udało się pobrać prognozy", async () => {
    mockApi({ overview: Object.assign(new Error("500"), { response: { status: 500 } }), period: notFound() });
    renderCard();

    expect((await screen.findByRole("status")).textContent).toMatch(/Nie udało się pobrać prognozy produkcji z paneli/);
  });
});
