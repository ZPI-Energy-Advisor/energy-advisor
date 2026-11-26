import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import apiClient from "../api/client";
import DashboardPvCard from "./DashboardPvCard";

const OVERVIEW = {
  today: "2026-11-26",
  days: [
    { date: "2026-11-26", available: true, total_kwh: 5.3 },
    { date: "2026-11-27", available: true, total_kwh: 2.04 },
  ],
};

const renderCard = () => render(<MemoryRouter><DashboardPvCard /></MemoryRouter>);

describe("DashboardPvCard", () => {
  afterEach(() => vi.restoreAllMocks());

  it("pokazuje jutrzejszą produkcję", async () => {
    vi.spyOn(apiClient, "get").mockResolvedValue({ data: OVERVIEW });
    renderCard();

    expect((await screen.findByRole("link")).textContent).toMatch(/Jutro z paneli ok\. 2,0 kWh\.Prognoza PV/);
  });

  it("bez instalacji PV w profilu nic nie pokazuje", async () => {
    const get = vi.spyOn(apiClient, "get").mockRejectedValue(Object.assign(new Error("404"), { response: { status: 404 } }));
    const { container } = renderCard();

    await vi.waitFor(() => expect(get).toHaveBeenCalled());
    await Promise.resolve();
    expect(container.textContent).toBe("");
  });
});
