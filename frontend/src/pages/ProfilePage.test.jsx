import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import apiClient from "../api/client";
import ProfilePage from "./ProfilePage";

vi.mock("../hooks/useCurrentUser", () => ({ useCurrentUser: () => ({ refresh: vi.fn() }) }));

const profile = {
  base_info: {
    type_of_property: "single_family_house",
    year_of_construction: 2010,
    heating_area_m2: 120,
    number_of_residents: 3,
    town: "Kraków",
    postal_code: "30-001",
    distribution_operator: "TAURON",
    phase_type: "1_phase",
    contracted_power_kw: 10,
    billing_cycle: 2,
    billing_period_start_date: "2025-01-01",
  },
  consumption_and_tariff: { tariff_type: "G13", dynamic_price: false },
  pv_config: { mode: "none" },
};

const options = {
  has_rates: true,
  tariffs: [
    { code: "G11", name: "G11", billing_cycles: [1, 2] },
    { code: "G12as", name: "G12as", billing_cycles: [1, 2] },
    { code: "G13", name: "G13", billing_cycles: [1, 2] },
  ],
  dynamic_offer: { name: "Prąd z Ceną Dynamiczną", distribution_groups: ["G11", "G13"], billing_cycle_months: 1 },
  billing_cycles: [1, 2],
  unsupported: [],
};

const renderPage = () => {
  vi.spyOn(apiClient, "get").mockImplementation((url) =>
    Promise.resolve({ data: url === "/tariffs/options" ? options : profile }),
  );
  render(<ProfilePage />);
};

describe("ProfilePage", () => {
  it("pozwala wybrać cenę dynamiczną obok grupy taryfowej i opisuje rozliczenie", async () => {
    renderPage();

    const checkbox = await screen.findByRole("checkbox", { name: /Umowa z ceną dynamiczną/ });
    fireEvent.click(checkbox);

    expect(checkbox.checked).toBe(true);
    expect(screen.getByText(/dystrybucja według grupy G13/)).toBeTruthy();
    expect(screen.getByText(/Oferta rozlicza się co 1 mies\./)).toBeTruthy();
    // Okres rozliczeniowy narzuca oferta: 1 miesiąc, bez możliwości zmiany.
    const cycle = screen.getByRole("combobox", { name: /Cykl rozliczeniowy/ });
    expect(cycle.value).toBe("1");
    expect(cycle.disabled).toBe(true);
  });

  it("przy grupie spoza oferty wyłącza cenę dynamiczną", async () => {
    renderPage();
    const checkbox = await screen.findByRole("checkbox", { name: /Umowa z ceną dynamiczną/ });
    fireEvent.click(checkbox);

    fireEvent.change(screen.getByRole("combobox", { name: "Grupa taryfowa" }), { target: { value: "G12as" } });

    expect(checkbox.checked).toBe(false);
    expect(checkbox.disabled).toBe(true);
    expect(screen.getByText("Oferta z ceną dynamiczną obejmuje grupy: G11, G13.")).toBeTruthy();
  });

  it("w net-billingu zapisuje wybór wyceny RCEm", async () => {
    renderPage();
    const put = vi.spyOn(apiClient, "put").mockResolvedValue({ data: profile });
    fireEvent.change(await screen.findByRole("combobox", { name: "Fotowoltaika" }), { target: { value: "net_billing" } });

    const pricing = screen.getByRole("combobox", { name: "Wycena energii oddanej" });
    expect(pricing.value).toBe("RCE");
    fireEvent.change(pricing, { target: { value: "RCEm" } });
    fireEvent.click(screen.getByRole("button", { name: "Zapisz profil" }));

    await vi.waitFor(() => expect(put).toHaveBeenCalled());
    expect(put.mock.calls[0][1].pv_config).toEqual({ mode: "net_billing", type_of_price: "RCEm" });
  });
});
