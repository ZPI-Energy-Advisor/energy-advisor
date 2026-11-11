import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
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

const tauronOptions = {
  has_rates: true,
  tariffs: [
    { code: "G11", name: "G11", zones_description: "jedna cena przez całą dobę", billing_cycles: [1, 2] },
    { code: "G12as", name: "G12as", zones_description: "tańsza energia 13–15 i 22–6", billing_cycles: [1, 2] },
    { code: "G13", name: "G13", zones_description: "najtańsza energia 13–16 i 21–7", billing_cycles: [1, 2] },
  ],
  dynamic_offer: { name: "Prąd z Ceną Dynamiczną", distribution_groups: ["G11", "G13"], billing_cycle_months: 1 },
  billing_cycles: [1, 2],
  unsupported: [],
};

const pgeOptions = {
  has_rates: true,
  tariffs: [
    { code: "G11", name: "G11", zones_description: "jedna cena przez całą dobę", billing_cycles: [1, 2, 6] },
    { code: "G12w", name: "G12w", zones_description: "tańsza energia 13–15 i 22–6 oraz cały weekend i święta", billing_cycles: [1, 2, 6] },
  ],
  dynamic_offer: null,
  billing_cycles: [1, 2, 6],
  unsupported: [],
};

const optionsByOperator = { TAURON: tauronOptions, PGE: pgeOptions };

const renderPage = (savedProfile = profile) => {
  vi.spyOn(apiClient, "get").mockImplementation((url, config) => {
    if (url === "/tariffs/options") return Promise.resolve({ data: optionsByOperator[config.params.operator] ?? { has_rates: false } });
    return typeof savedProfile === "function" ? savedProfile() : Promise.resolve({ data: savedProfile });
  });
  render(<ProfilePage />);
};

// Taryfy pojawiają się po dwóch zapytaniach (profil, potem opcje operatora): przy pełnym przebiegu testów trwa to dłużej.
const tariffRadio = (code) => screen.findByRole("radio", { name: new RegExp(`^${code}\\b`) }, { timeout: 5000 });

afterEach(() => vi.restoreAllMocks());

describe("ProfilePage", () => {
  it("pokazuje taryfy operatora z opisem stref", async () => {
    renderPage();

    const g13 = await tariffRadio("G13");
    expect(g13.checked).toBe(true);
    expect(screen.getByText("najtańsza energia 13–16 i 21–7")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Przyłącze i rozliczenie" })).toBeTruthy();
  });

  it("po zmianie operatora pokazuje tylko jego taryfy i oznacza niedostępną", async () => {
    renderPage();
    await tariffRadio("G13");

    fireEvent.change(screen.getByLabelText("Operator dystrybucyjny"), { target: { value: "PGE" } });

    expect(await tariffRadio("G12w")).toBeTruthy();
    expect(screen.queryByRole("radio", { name: /^G12as\b/ })).toBeNull();
    const g13 = screen.getByRole("radio", { name: /^G13\b/ });
    expect(g13.checked).toBe(true);
    expect(screen.getByText("Niedostępna u operatora PGE Dystrybucja.")).toBeTruthy();

    // Zapis z niedostępną taryfą zatrzymuje formularz z błędem przy polu.
    const put = vi.spyOn(apiClient, "put");
    fireEvent.click(screen.getByRole("button", { name: "Zapisz profil" }));
    expect(put).not.toHaveBeenCalled();
    expect(screen.getAllByText("Taryfa G13 jest niedostępna u tego operatora.").length).toBeGreaterThan(0);
    expect(screen.getByText("Nie zapisano – popraw błędy powyżej.")).toBeTruthy();

    fireEvent.click(screen.getByRole("radio", { name: /^G12w\b/ }));
    expect(screen.queryByText("Niedostępna u operatora PGE Dystrybucja.")).toBeNull();
  });

  it("pilnuje formatu kodu pocztowego i pokazuje błąd przy polu", async () => {
    renderPage();
    const postal = await screen.findByLabelText("Kod pocztowy");

    fireEvent.change(postal, { target: { value: "30a12" } });
    expect(postal.value).toBe("30-12");

    fireEvent.click(screen.getByRole("button", { name: "Zapisz profil" }));

    expect(postal.getAttribute("aria-invalid")).toBe("true");
    expect(screen.getAllByText("Kod pocztowy w formacie 00-000.").length).toBeGreaterThan(0);

    fireEvent.change(postal, { target: { value: "30123" } });
    expect(postal.value).toBe("30-123");
    expect(postal.getAttribute("aria-invalid")).toBe("false");
  });

  it("błąd 422 z backendu pokazuje przy polu, a nie surowe dane", async () => {
    renderPage();
    await tariffRadio("G13");
    vi.spyOn(apiClient, "put").mockRejectedValue({
      response: {
        status: 422,
        data: {
          detail: [
            { loc: ["body", "base_info", "contracted_power_kw"], msg: "Input should be greater than 0", type: "greater_than" },
            { loc: ["body", "base_info", "billing_cycle"], msg: "Operator TAURON nie ma w cenniku okresu rozliczeniowego 2 mies.", type: "value_error" },
          ],
        },
      },
    });

    fireEvent.click(screen.getByRole("button", { name: "Zapisz profil" }));

    const power = screen.getByLabelText("Moc umowna");
    await vi.waitFor(() => expect(power.getAttribute("aria-invalid")).toBe("true"));
    // Przy polu i w liście pól nad formularzem.
    expect(screen.getByText("Moc umowna musi być większa niż 0 kW.").id).toBe(power.getAttribute("aria-describedby").split(" ")[0]);
    expect(screen.getByText("Operator TAURON nie ma w cenniku okresu rozliczeniowego 2 mies.")).toBeTruthy();
    const summary = screen.getByText("Popraw pola:").parentElement;
    expect(summary.textContent).toContain("Moc umowna: Moc umowna musi być większa niż 0 kW.");
    expect(summary.textContent).toContain("Cykl rozliczeniowy: Operator TAURON nie ma w cenniku");
    expect(screen.queryByText(/greater_than|Input should/)).toBeNull();
    // Każdy link z listy prowadzi do istniejącego pola, także do pól z kilku przycisków (cykl).
    for (const link of summary.querySelectorAll("a")) {
      expect(document.getElementById(link.getAttribute("href").slice(1))).not.toBeNull();
    }
  });

  it("zapisuje profil z liczbami wpisanymi z przecinkiem", async () => {
    renderPage();
    const put = vi.spyOn(apiClient, "put").mockResolvedValue({ data: profile });
    fireEvent.change(await screen.findByLabelText("Powierzchnia ogrzewana"), { target: { value: "120,5" } });
    fireEvent.change(screen.getByLabelText("Rok budowy"), { target: { value: "1998" } });
    fireEvent.click(screen.getByRole("button", { name: "Więcej" }));
    fireEvent.click(screen.getByRole("button", { name: "3 fazy" }));

    fireEvent.click(screen.getByRole("button", { name: "Zapisz profil" }));

    await vi.waitFor(() => expect(put).toHaveBeenCalled());
    expect(put.mock.calls[0][1].base_info).toMatchObject({
      heating_area_m2: 120.5,
      year_of_construction: 1998,
      number_of_residents: 4,
      phase_type: "3_phase",
      postal_code: "30-001",
    });
    expect(await screen.findByText("Profil zapisany.")).toBeTruthy();
  });

  it("profil w starszym formacie wczytuje dane i oznacza brakujące pola", async () => {
    const oldBase = { ...profile.base_info };
    delete oldBase.billing_period_start_date;
    renderPage(() => Promise.reject({
      response: {
        status: 409,
        data: {
          detail: {
            message: "Profil użytkownika wymaga ponownego uzupełnienia.",
            profile: { ...profile, base_info: oldBase },
            fields: ["base_info.billing_period_start_date"],
          },
        },
      },
    }));

    expect(await screen.findByText("Profil wymaga uzupełnienia: Początek okresu rozliczeniowego.")).toBeTruthy();
    expect(screen.getByLabelText("Miejscowość").value).toBe("Kraków");
    expect(screen.getByText("Brak w zapisanym profilu.")).toBeTruthy();

    fireEvent.change(screen.getByLabelText("Początek okresu rozliczeniowego"), { target: { value: "2026-01-01" } });
    expect(screen.queryByText("Brak w zapisanym profilu.")).toBeNull();
  });

  it("pozwala wybrać cenę dynamiczną obok grupy taryfowej i opisuje rozliczenie", async () => {
    renderPage();

    const checkbox = await screen.findByRole("checkbox", { name: /Umowa z ceną dynamiczną/ });
    fireEvent.click(checkbox);

    expect(checkbox.checked).toBe(true);
    expect(screen.getByText(/dystrybucja według grupy G13/)).toBeTruthy();
    // Okres rozliczeniowy narzuca oferta: 1 miesiąc, bez możliwości zmiany.
    const cycle = screen.getByRole("group", { name: "Cykl rozliczeniowy" });
    expect(within(cycle).getByRole("button", { name: "1 mies.", pressed: true })).toBeTruthy();
    expect(within(cycle).getByRole("button", { name: "2 mies." }).disabled).toBe(true);
  });

  it("przy grupie spoza oferty wyłącza cenę dynamiczną", async () => {
    renderPage();
    const checkbox = await screen.findByRole("checkbox", { name: /Umowa z ceną dynamiczną/ });
    fireEvent.click(checkbox);

    fireEvent.click(screen.getByRole("radio", { name: /^G12as\b/ }));

    expect(checkbox.checked).toBe(false);
    expect(checkbox.disabled).toBe(true);
    expect(screen.getByText("Oferta z ceną dynamiczną obejmuje grupy: G11, G13.")).toBeTruthy();
  });

  it("w net-billingu zapisuje wybór wyceny RCEm", async () => {
    renderPage();
    const put = vi.spyOn(apiClient, "put").mockResolvedValue({ data: profile });
    fireEvent.click(await screen.findByRole("radio", { name: /^Net-billing/ }));

    expect(screen.getByRole("radio", { name: /^RCE\b/ }).checked).toBe(true);
    fireEvent.click(screen.getByRole("radio", { name: /^RCEm/ }));
    fireEvent.click(screen.getByRole("button", { name: "Zapisz profil" }));

    await vi.waitFor(() => expect(put).toHaveBeenCalled());
    expect(put.mock.calls[0][1].pv_config).toEqual({ mode: "net_billing", type_of_price: "RCEm" });
  });
});
