import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import apiClient from "../api/client";
import TomorrowPriceCards from "./TomorrowPriceCards";
import { CurrentUserContext } from "../context/currentUserContext";

const AVAILABLE = {
  status: "available",
  business_date: "2026-11-17",
  window_minutes: 120,
  tariff: "TAURON, G11 z ceną dynamiczną",
  profile_dynamic: true,
  average_price_pln_kwh: 0.615,
  flat_prices: false,
  cheapest: {
    start: "2026-11-17T10:00:00+01:00",
    end: "2026-11-17T12:00:00+01:00",
    average_price_pln_kwh: 0.4,
    difference_percent: -35.0,
  },
  most_expensive: {
    start: "2026-11-17T17:15:00+01:00",
    end: "2026-11-17T19:15:00+01:00",
    average_price_pln_kwh: 1.234,
    difference_percent: 100.7,
  },
  expected_publication_at: null,
};
const UNAVAILABLE = {
  ...AVAILABLE,
  status: "unavailable",
  average_price_pln_kwh: null,
  flat_prices: null,
  cheapest: null,
  most_expensive: null,
  expected_publication_at: "2026-11-16T15:00:00+01:00",
};

const renderCards = (response, { tariffType = "G11", profileExists = true } = {}) => {
  const get = vi
    .spyOn(apiClient, "get")
    .mockImplementation(() => (response instanceof Error ? Promise.reject(response) : Promise.resolve({ data: response })));
  render(
    <MemoryRouter>
      <CurrentUserContext.Provider value={{ profileTariff: { exists: profileExists, tariff_type: profileExists ? tariffType : null } }}>
        <TomorrowPriceCards />
      </CurrentUserContext.Provider>
    </MemoryRouter>,
  );
  return get;
};

describe("TomorrowPriceCards", () => {
  it("pokazuje dwie karty w różnych kolorach z godzinami i średnią ceną", async () => {
    const get = renderCards(AVAILABLE);

    const cheapest = await screen.findByTestId("price-card-cheapest");
    expect(cheapest.textContent).toBe("Jutro najtaniej10:00–12:00średnio 0,40 zł/kWh");
    expect(cheapest.className).toContain("emerald");

    const expensive = screen.getByTestId("price-card-most_expensive");
    expect(expensive.textContent).toBe("Jutro najdrożej17:15–19:15średnio 1,23 zł/kWh");
    expect(expensive.className).toContain("rose");

    expect(get).toHaveBeenCalledWith("/dynamic-prices/tomorrow/insights", { params: { window: "2h" } });
    // Klient z ceną dynamiczną nie dostaje dopisku o innej taryfie.
    expect(screen.queryByText(/To ceny taryfy dynamicznej/)).toBeNull();
  });

  it("przy płaskich cenach zamiast kart mówi, że pora nie ma znaczenia", async () => {
    renderCards({ ...AVAILABLE, flat_prices: true });

    expect(await screen.findByText(/Jutro cena prądu prawie się nie zmienia: przez cały dzień ok. 0,62 zł\/kWh/)).toBeTruthy();
    expect(screen.queryByTestId("price-card-cheapest")).toBeNull();
  });

  it("przed publikacją zapowiada godzinę pojawienia się cen", async () => {
    vi.useFakeTimers({ toFake: ["Date"], now: new Date("2026-11-16T09:00:00+01:00") });
    renderCards(UNAVAILABLE);

    expect(await screen.findByText("Ceny na jutro pojawią się ok. 15:00.")).toBeTruthy();
    vi.useRealTimers();
  });

  it("po spodziewanej godzinie mówi o opóźnieniu zamiast obiecywać minioną godzinę", async () => {
    vi.useFakeTimers({ toFake: ["Date"], now: new Date("2026-11-16T16:30:00+01:00") });
    renderCards(UNAVAILABLE);

    expect(await screen.findByText(/Cen na jutro jeszcze nie ma, choć zwykle są ok. 15:00/)).toBeTruthy();
    vi.useRealTimers();
  });

  it("użytkownikowi z inną taryfą dopisuje, że to taryfa dynamiczna, z linkiem do analizy taryf", async () => {
    renderCards({ ...AVAILABLE, profile_dynamic: false }, { tariffType: "G12" });

    await screen.findByTestId("price-card-cheapest");
    const note = screen.getByText(/To ceny taryfy dynamicznej, a Ty masz taryfę G12/);
    expect(within(note).getByRole("link", { name: "Sprawdź w analizie taryf" }).getAttribute("href")).toBe("/tariffs");
  });

  it("dopisek o taryfie dynamicznej jest też przy braku cen", async () => {
    renderCards({ ...UNAVAILABLE, profile_dynamic: false }, { tariffType: "G12" });

    expect(await screen.findByText(/To ceny taryfy dynamicznej/)).toBeTruthy();
  });

  it("bez cennika na jutro mówi o tym wprost, bez godziny publikacji i bez dopisku o analizie taryf", async () => {
    renderCards({ ...UNAVAILABLE, status: "no_tariff_data", expected_publication_at: null, profile_dynamic: false });

    expect(await screen.findByText(/Nie mamy jeszcze cennika taryfy dynamicznej Twojego operatora na jutro/)).toBeTruthy();
    expect(screen.queryByText(/pojawią się/)).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByText(/To ceny taryfy dynamicznej/)).toBeNull();
  });

  it("przy niepełnym profilu prosi o jego uzupełnienie", async () => {
    renderCards(Object.assign(new Error("409"), { response: { status: 409, data: { detail: "Uzupełnij profil…" } } }));

    expect((await screen.findByRole("link", { name: "Uzupełnij profil" })).getAttribute("href")).toBe("/profile");
  });

  it("bez profilu nic nie pokazuje, bo o profil prosi już baner nad kartami", async () => {
    const get = renderCards(Object.assign(new Error("409"), { response: { status: 409, data: { detail: "Uzupełnij profil…" } } }), {
      profileExists: false,
    });

    await waitFor(() => expect(get).toHaveBeenCalled());
    await waitFor(() => expect(screen.queryByText(/Sprawdzamy ceny na jutro/)).toBeNull());
    expect(screen.queryByRole("region", { name: "Ceny prądu na jutro" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Uzupełnij profil" })).toBeNull();
  });

  it("przed publikacją cen na jutro pokazuje okna z reszty dzisiejszej doby i zapowiedź cen na jutro", async () => {
    const get = vi.spyOn(apiClient, "get").mockImplementation((url) =>
      Promise.resolve({ data: url.includes("/today/") ? { ...AVAILABLE, business_date: "2026-11-16" } : UNAVAILABLE }),
    );
    render(
      <MemoryRouter>
        <CurrentUserContext.Provider value={{ profileTariff: { exists: true, tariff_type: "G11" } }}>
          <TomorrowPriceCards />
        </CurrentUserContext.Provider>
      </MemoryRouter>,
    );

    const cheapest = await screen.findByTestId("price-card-cheapest");
    expect(cheapest.textContent).toMatch(/^Dziś najtaniej \(do końca dnia\)10:00–12:00/);
    expect(screen.getByTestId("price-card-most_expensive").textContent).toMatch(/^Dziś najdrożej/);
    expect(screen.getByText(/Ceny na jutro|Cen na jutro jeszcze nie ma/)).toBeTruthy();
    expect(get).toHaveBeenCalledWith("/dynamic-prices/today/insights", { params: { window: "2h" } });
  });

  it("pokazuje błąd pobrania i pozwala ponowić", async () => {
    const get = renderCards(Object.assign(new Error("500"), { response: { status: 500, data: {} } }));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Nie udało się pobrać cen na jutro.");
    get.mockResolvedValue({ data: AVAILABLE });
    fireEvent.click(within(alert).getByRole("button", { name: "Spróbuj ponownie" }));

    expect(await screen.findByTestId("price-card-cheapest")).toBeTruthy();
  });
});
