import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import apiClient from "../api/client";
import DashboardPvPeriod from "./DashboardPvPeriod";

const PERIOD = {
  date_from: "2026-10-01", date_to: "2026-10-30", days: 30, model_days: 28, model_kwh: 112.44,
  actual_kwh: 98.1, export_kwh: null, estimated_installation: false, approximate_location: false,
};
const RANGE = { from: "2026-10-01", to: "2026-10-30" };

const renderCard = () => render(<MemoryRouter><DashboardPvPeriod range={RANGE} /></MemoryRouter>);

describe("DashboardPvPeriod", () => {
  afterEach(() => vi.restoreAllMocks());

  it("szacunek z pogody obok produkcji z pliku urządzeń", async () => {
    const get = vi.spyOn(apiClient, "get").mockResolvedValue({ data: PERIOD });
    renderCard();

    const card = await screen.findByRole("region", { name: "Panele w tym okresie" });
    expect(get).toHaveBeenCalledWith("/pv/period", { params: RANGE });
    expect(card.textContent).toContain("ok. 112,4 kWh");
    expect(card.textContent).toContain("Pogoda dla 28 z 30 dni z plików: obie liczby są z tych samych dni.");
    expect(card.textContent).toContain("Produkcja z pliku urządzeń98,1 kWh");
    expect(screen.queryByText(/szacunkowe/)).toBeNull();
  });

  it("przy pliku z licznika pokazuje oddanie i dopiski z linkiem do profilu", async () => {
    vi.spyOn(apiClient, "get").mockResolvedValue({
      data: { ...PERIOD, model_days: 30, actual_kwh: null, export_kwh: 40.2, estimated_installation: true, approximate_location: true },
    });
    renderCard();

    const card = await screen.findByRole("region", { name: "Panele w tym okresie" });
    expect(card.textContent).toContain("Oddane do sieci (licznik)40,2 kWh");
    expect(card.textContent).toContain("Szacunek orientacyjny");
    expect(card.textContent).toContain("Pogoda dla regionu");
    expect(screen.getByRole("link", { name: "Uzupełnij panele w profilu" }).getAttribute("href")).toBe("/profile");
  });

  it("bez paneli albo pogody nic nie pokazuje", async () => {
    const get = vi.spyOn(apiClient, "get").mockRejectedValue(new Error("404"));
    const { container } = renderCard();

    await vi.waitFor(() => expect(get).toHaveBeenCalled());
    expect(container.innerHTML).toBe("");
  });
});
