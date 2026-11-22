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
    expect(put.mock.calls[0][1].pv_config).toEqual({
      mode: "net_billing",
      type_of_price: "RCEm",
      installation: { arrays: [{ power_kwp: 6, azimuth: 0, tilt: 35 }], estimated: true },
    });
  });

  it("zapisuje panele grupami: 4 na południe i 3 na wschód", async () => {
    renderPage();
    const put = vi.spyOn(apiClient, "put").mockResolvedValue({ data: profile });
    fireEvent.click(await screen.findByRole("radio", { name: /^Net-billing/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: /Nie znam parametrów paneli/ }));
    fireEvent.click(screen.getByRole("button", { name: "Liczba paneli" }));

    fireEvent.change(screen.getByLabelText("Liczba paneli"), { target: { value: "4" } });
    fireEvent.click(screen.getByRole("button", { name: "+ Dodaj grupę paneli" }));
    const second = screen.getByRole("group", { name: /Grupa paneli 2/ });
    fireEvent.change(within(second).getByLabelText("Liczba paneli"), { target: { value: "3" } });
    fireEvent.change(within(second).getByLabelText("Kierunek"), { target: { value: "-90" } });

    expect(screen.getByText("Razem: 3,01 kWp")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Zapisz profil" }));

    await vi.waitFor(() => expect(put).toHaveBeenCalled());
    expect(put.mock.calls[0][1].pv_config.installation).toEqual({
      arrays: [
        { azimuth: 0, tilt: 35, panel_count: 4 },
        { azimuth: -90, tilt: 35, panel_count: 3 },
      ],
      panel_power_w: 430,
      inverter_power_kw: null,
      estimated: false,
    });
  });

  it("pokazuje błąd grupy paneli przy polu i w podsumowaniu", async () => {
    renderPage();
    const put = vi.spyOn(apiClient, "put");
    fireEvent.click(await screen.findByRole("radio", { name: /^Net-metering/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: /Nie znam parametrów paneli/ }));
    fireEvent.change(screen.getByLabelText("Nachylenie"), { target: { value: "95" } });
    fireEvent.click(screen.getByRole("button", { name: "Zapisz profil" }));

    expect(await screen.findByRole("link", { name: "Grupa paneli 1: nachylenie" })).toBeTruthy();
    expect(screen.getByLabelText("Nachylenie").getAttribute("aria-invalid")).toBe("true");
    expect(put).not.toHaveBeenCalled();
  });

  it("pokazuje lokalizację wyznaczoną z kodu i ostrzega o przybliżonej", async () => {
    const located = {
      ...profile,
      base_info: {
        ...profile.base_info,
        location: { latitude: 50.0614, longitude: 19.9366, source: "postal_code", label: "Kraków", address: "30-001 Kraków", approximate: false },
      },
    };
    renderPage(located);

    expect(await screen.findByText("Kraków, 30-001")).toBeTruthy();
    expect(screen.getByText(/50,0614° N, 19,9366° E/)).toBeTruthy();

    fireEvent.change(screen.getByLabelText("Miejscowość"), { target: { value: "Wieliczka" } });
    expect(screen.getByText(/Adres się zmienił/)).toBeTruthy();
  });

  it("przybliżona lokalizacja ma ostrzeżenie", async () => {
    renderPage({
      ...profile,
      base_info: {
        ...profile.base_info,
        location: { latitude: 50.0647, longitude: 19.945, source: "postal_region", label: "Kraków", address: "30-001 Kraków", approximate: true },
      },
    });

    expect(await screen.findByText("Okolice: Kraków")).toBeTruthy();
    expect(screen.getByText(/przybliżona dla całego regionu/)).toBeTruthy();
  });

  it("pokazuje przy polu błąd niepasującej miejscowości z backendu", async () => {
    renderPage();
    const detail = [
      {
        loc: ["body", "base_info", "town"],
        msg: "Miejscowość Wronki nie pasuje do kodu pocztowego 51-515. Ten kod to okolice: Wrocław.",
        type: "value_error",
      },
    ];
    vi.spyOn(apiClient, "put").mockRejectedValue({ response: { status: 422, data: { detail } } });

    fireEvent.click(await screen.findByRole("button", { name: "Zapisz profil" }));

    expect(await screen.findByText("Miejscowość Wronki nie pasuje do kodu pocztowego 51-515. Ten kod to okolice: Wrocław.")).toBeTruthy();
    expect(screen.getByLabelText("Miejscowość").getAttribute("aria-invalid")).toBe("true");
  });

  it("lokalizacja z przeglądarki trafia do zapisu jako wskazana ręcznie, a można wrócić do kodu", async () => {
    const getCurrentPosition = vi.fn((success) => success({ coords: { latitude: 50.012345, longitude: 20.054321 } }));
    vi.stubGlobal("navigator", { ...navigator, geolocation: { getCurrentPosition } });
    renderPage();
    const put = vi.spyOn(apiClient, "put").mockResolvedValue({ data: profile });

    fireEvent.click(await screen.findByRole("button", { name: "Użyj mojej lokalizacji" }));
    expect(screen.getByText("Położenie wskazane przez Ciebie")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Zapisz profil" }));

    await vi.waitFor(() => expect(put).toHaveBeenCalledTimes(1));
    expect(put.mock.calls[0][1].base_info.location).toEqual({
      latitude: 50.0123,
      longitude: 20.0543,
      source: "manual",
      label: null,
      address: "30-001 Kraków",
    });

    fireEvent.click(await screen.findByRole("button", { name: "Użyj mojej lokalizacji" }));
    fireEvent.click(screen.getByRole("button", { name: "Wyznacz z kodu pocztowego" }));
    fireEvent.click(await screen.findByRole("button", { name: "Zapisz profil" }));
    await vi.waitFor(() => expect(put).toHaveBeenCalledTimes(2));
    expect(put.mock.calls[1][1].base_info.location).toBeNull();
    vi.unstubAllGlobals();
  });

  it("położenie poza Polską nie zmienia lokalizacji", async () => {
    vi.stubGlobal("navigator", { ...navigator, geolocation: { getCurrentPosition: (success) => success({ coords: { latitude: 48.2, longitude: 16.37 } }) } });
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Użyj mojej lokalizacji" }));

    expect(screen.getByText(/poza Polską/)).toBeTruthy();
    expect(screen.getByText(/pokażemy, gdzie jest dom/)).toBeTruthy();
    vi.unstubAllGlobals();
  });

  it("z samego kodu pocztowego po Enterze uzupełnia miejscowość i pokazuje lokalizację bez zapisu", async () => {
    renderPage({ ...profile, base_info: { ...profile.base_info, town: "", postal_code: "" } });
    const lookup = {
      status: "found",
      town: "Wronki",
      postal_code: "64-510",
      location: { latitude: 52.71, longitude: 16.3743, source: "postal_code", label: "Wronki", address: "64-510 Wronki", approximate: false },
      errors: {},
      message: "Uzupełniliśmy miejscowość z kodu pocztowego.",
    };
    const get = apiClient.get.getMockImplementation();
    apiClient.get.mockImplementation((url, config) =>
      url.endsWith("/address-lookup") ? Promise.resolve({ data: lookup }) : get(url, config),
    );
    const put = vi.spyOn(apiClient, "put");

    const postal = await screen.findByLabelText("Kod pocztowy");
    fireEvent.change(postal, { target: { value: "64510" } });
    fireEvent.keyDown(postal, { key: "Enter" });

    expect(await screen.findByText("Wronki, 64-510")).toBeTruthy();
    expect(screen.getByLabelText("Miejscowość").value).toBe("Wronki");
    expect(screen.getByText("Uzupełniliśmy miejscowość z kodu pocztowego.")).toBeTruthy();
    expect(apiClient.get).toHaveBeenCalledWith("/users/me/profile/address-lookup", { params: { postal_code: "64-510" } });
    expect(put).not.toHaveBeenCalled();
  });

  it("po wyjściu z pola miejscowości uzupełnia kod, a niepasujący adres oznacza przy polu", async () => {
    renderPage({ ...profile, base_info: { ...profile.base_info, town: "", postal_code: "" } });
    const responses = {
      Smolec: { status: "found", town: "Smolec", postal_code: "55-080", location: { latitude: 51.07, longitude: 16.88, source: "postal_code", label: "Smolec" }, errors: {} },
      Wronki: { status: "invalid", errors: { town: "Miejscowość Wronki nie pasuje do kodu pocztowego 55-080." } },
    };
    const get = apiClient.get.getMockImplementation();
    apiClient.get.mockImplementation((url, config) =>
      url.endsWith("/address-lookup") ? Promise.resolve({ data: responses[config.params.town] }) : get(url, config),
    );

    const town = await screen.findByLabelText("Miejscowość");
    fireEvent.change(town, { target: { value: "Smolec" } });
    fireEvent.blur(town);
    await vi.waitFor(() => expect(screen.getByLabelText("Kod pocztowy").value).toBe("55-080"));

    fireEvent.change(town, { target: { value: "Wronki" } });
    fireEvent.blur(town);

    expect(await screen.findByText("Miejscowość Wronki nie pasuje do kodu pocztowego 55-080.")).toBeTruthy();
    expect(town.getAttribute("aria-invalid")).toBe("true");
  });

  it("pyta przed wyjściem z niezapisanymi zmianami i nie pyta po zapisie", async () => {
    renderPage();
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    vi.spyOn(apiClient, "put").mockImplementation((url, payload) => Promise.resolve({ data: { ...profile, base_info: { ...profile.base_info, ...payload.base_info } } }));
    const link = document.createElement("a");
    link.href = "/dashboard";
    link.textContent = "Dashboard";
    document.body.appendChild(link);
    const clickLink = () => link.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, button: 0 }));

    fireEvent.change(await screen.findByLabelText("Powierzchnia ogrzewana"), { target: { value: "130" } });
    expect(screen.getByText("Masz niezapisane zmiany.")).toBeTruthy();
    expect(clickLink()).toBe(false);
    expect(confirm).toHaveBeenCalledWith("Masz niezapisane zmiany w profilu. Wyjść bez zapisywania?");

    fireEvent.click(screen.getByRole("button", { name: "Zapisz profil" }));
    await screen.findByText("Profil zapisany.");
    confirm.mockClear();

    expect(clickLink()).toBe(true);
    expect(confirm).not.toHaveBeenCalled();
    link.remove();
  });

  it("cofa niezapisane zmiany do zapisanego profilu", async () => {
    renderPage();
    const area = await screen.findByLabelText("Powierzchnia ogrzewana");
    const saved = area.value;
    expect(screen.getByText("Wszystkie zmiany są zapisane.")).toBeTruthy();

    fireEvent.change(area, { target: { value: "130" } });
    fireEvent.click(screen.getByRole("button", { name: "Cofnij zmiany" }));

    expect(area.value).toBe(saved);
    expect(screen.queryByRole("button", { name: "Cofnij zmiany" })).toBeNull();
    expect(screen.getByText("Wszystkie zmiany są zapisane.")).toBeTruthy();
  });
});
