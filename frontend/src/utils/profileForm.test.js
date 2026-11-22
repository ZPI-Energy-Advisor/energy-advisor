import { describe, expect, it } from "vitest";
import {
  createArray,
  createEmptyProfile,
  fieldLabel,
  formatPostalCode,
  parseDecimal,
  parseSaveError,
  profileFromSaved,
  profileSnapshot,
  toPayload,
  typicalInstallation,
  validateProfile,
  withAddressLookup,
} from "./profileForm";

const filledProfile = (pv) => ({
  ...createEmptyProfile(),
  base_info: {
    ...createEmptyProfile().base_info,
    year_of_construction: "2010",
    heating_area_m2: "120",
    town: "Wrocław",
    postal_code: "50-370",
    contracted_power_kw: "11",
    billing_period_start_date: "2026-01-01",
  },
  pv_config: pv,
});

const installation = (changes) => ({ ...typicalInstallation(), estimated: false, ...changes });

describe("profileForm", () => {
  it("formatuje kod pocztowy podczas wpisywania", () => {
    expect(formatPostalCode("3")).toBe("3");
    expect(formatPostalCode("30")).toBe("30");
    expect(formatPostalCode("301")).toBe("30-1");
    expect(formatPostalCode("30-0012")).toBe("30-001");
    expect(formatPostalCode("ab30 001")).toBe("30-001");
  });

  it("czyta liczby z przecinkiem i odrzuca tekst", () => {
    expect(parseDecimal("12,5")).toBe(12.5);
    expect(parseDecimal(" 7 ")).toBe(7);
    expect(parseDecimal("")).toBeNaN();
    expect(parseDecimal("1,2,3")).toBeNaN();
  });

  it("waliduje pola przed wysłaniem", () => {
    const errors = validateProfile(createEmptyProfile(), { offeredTariffs: ["G12"] });

    expect(errors).toMatchObject({
      "base_info.year_of_construction": "Wybierz rok budowy.",
      "base_info.heating_area_m2": "Podaj liczbę.",
      "base_info.postal_code": "Kod pocztowy w formacie 00-000.",
      "base_info.town": "Podaj miejscowość.",
      "consumption_and_tariff.tariff_type": "Taryfa G11 jest niedostępna u tego operatora.",
    });
    expect(errors["base_info.number_of_residents"]).toBeUndefined();
  });

  it("starszy profil z taryfą „dynamic” to G11 z ceną dynamiczną, braki uzupełnia domyślnymi", () => {
    const profile = profileFromSaved({ base_info: { town: "Gdańsk" }, consumption_and_tariff: { tariff_type: "dynamic" } });

    expect(profile.consumption_and_tariff).toEqual({ tariff_type: "G11", dynamic_price: true });
    expect(profile.base_info.town).toBe("Gdańsk");
    expect(profile.base_info.billing_cycle).toBe(2);
    expect(profile.pv_config).toEqual({ mode: "none" });
  });

  it("zamienia błędy 422 na komunikaty pól, także wewnątrz konfiguracji PV", () => {
    const error = {
      response: {
        data: {
          detail: [
            { loc: ["body", "base_info", "postal_code"], msg: "String should match pattern", type: "string_pattern_mismatch" },
            { loc: ["body", "pv_config", "net_metering", "installation", "arrays", 1, "tilt"], msg: "Input should be less than or equal to 90", type: "less_than_equal" },
            { loc: ["body", "pv_config", "net_billing", "installation"], msg: "Value error, Łączna moc paneli to najwyżej 50 kWp (mikroinstalacja).", type: "value_error" },
            { loc: ["body", "pv_config", "net_billing", "installation", "panel_power_w"], msg: "Input should be less than or equal to 1000", type: "less_than_equal" },
            { loc: ["body", "consumption_and_tariff", "tariff_type"], msg: "Operator PGE nie ma w cenniku taryfy G13.", type: "value_error" },
          ],
        },
      },
    };

    expect(parseSaveError(error)).toEqual({
      fields: {
        "base_info.postal_code": "Kod pocztowy w formacie 00-000.",
        "pv_config.arrays.1.tilt": "Nieprawidłowa wartość.",
        "pv_config.installation": "Łączna moc paneli to najwyżej 50 kWp (mikroinstalacja).",
        "pv_config.panel_power_w": "Moc panelu od 50 do 1000 W.",
        "consumption_and_tariff.tariff_type": "Operator PGE nie ma w cenniku taryfy G13.",
      },
      message: null,
    });
    expect(parseSaveError({ response: { data: { detail: "Coś poszło nie tak." } } })).toEqual({ fields: {}, message: "Coś poszło nie tak." });
    expect(parseSaveError({})).toEqual({ fields: {}, message: "Nie udało się zapisać profilu." });
  });

  it("nazywa pola grup paneli numerem grupy", () => {
    expect(fieldLabel("pv_config.arrays.1.panel_count")).toBe("Grupa paneli 2: liczba paneli");
    expect(fieldLabel("base_info.town")).toBe("Miejscowość");
  });

  it("dawny net-metering z samą mocą to jedna grupa na południe, profil bez paneli dostaje typową instalację", () => {
    const metering = profileFromSaved({ pv_config: { mode: "net_metering", power_of_pv_kwp: 12.5 } }).pv_config.installation;
    const billing = profileFromSaved({ pv_config: { mode: "net_billing", type_of_price: "RCE" } }).pv_config.installation;

    expect([metering.estimated, metering.arrays[0].power_kwp, metering.arrays[0].azimuth, metering.arrays[0].tilt]).toEqual([false, "12,5", 0, "35"]);
    expect([billing.estimated, billing.arrays[0].power_kwp]).toEqual([true, "6"]);
  });

  it("wysyła panele grupami: liczba paneli × moc panelu, kierunek i nachylenie", () => {
    const pv = {
      mode: "net_billing",
      type_of_price: "RCE",
      installation: installation({
        input: "panels",
        panel_power_w: "430",
        inverter_power_kw: "5,5",
        arrays: [createArray({ panel_count: 4, azimuth: 0, tilt: 35 }), createArray({ panel_count: 3, azimuth: -90, tilt: 30 })],
      }),
    };

    expect(validateProfile(filledProfile(pv))).toEqual({});
    expect(toPayload(filledProfile(pv)).pv_config).toEqual({
      mode: "net_billing",
      type_of_price: "RCE",
      installation: {
        arrays: [
          { azimuth: 0, tilt: 35, panel_count: 4 },
          { azimuth: -90, tilt: 30, panel_count: 3 },
        ],
        panel_power_w: 430,
        inverter_power_kw: 5.5,
        estimated: false,
      },
    });
  });

  it("bez znajomości parametrów wysyła typową instalację, nawet gdy pola są puste", () => {
    const pv = { mode: "net_metering", installation: { ...typicalInstallation(), arrays: [createArray({ power_kwp: "" })] } };

    expect(validateProfile(filledProfile(pv))).toEqual({});
    expect(toPayload(filledProfile(pv)).pv_config).toEqual({
      mode: "net_metering",
      installation: { arrays: [{ power_kwp: 6, azimuth: 0, tilt: 35 }], estimated: true },
    });
  });

  it("sprawdza moc, liczbę paneli, nachylenie i łączną moc", () => {
    const byPower = installation({ arrays: [createArray({ power_kwp: "0", tilt: 91 }), createArray({ power_kwp: "6" })] });
    const byPanels = installation({ input: "panels", panel_power_w: "20", arrays: [createArray({ panel_count: "" })] });
    const tooBig = installation({ arrays: [createArray({ power_kwp: "30" }), createArray({ power_kwp: "25" })], inverter_power_kw: "abc" });

    expect(validateProfile(filledProfile({ mode: "net_billing", installation: byPower }))).toEqual({
      "pv_config.arrays.0.power_kwp": "Wartość musi być większa od 0.",
      "pv_config.arrays.0.tilt": "Od 0 do 90°.",
    });
    expect(validateProfile(filledProfile({ mode: "net_billing", installation: byPanels }))).toEqual({
      "pv_config.panel_power_w": "Od 50 do 1000 W.",
      "pv_config.arrays.0.panel_count": "Podaj liczbę całkowitą.",
    });
    expect(validateProfile(filledProfile({ mode: "net_billing", installation: tooBig }))).toEqual({
      "pv_config.installation": "Łączna moc paneli to najwyżej 50 kWp (mikroinstalacja).",
      "pv_config.inverter_power_kw": "Podaj liczbę.",
    });
  });

  it("wynik sprawdzenia adresu poprawia pisownię, uzupełnia puste pole i nie nadpisuje nowszych zmian", () => {
    const location = { latitude: 51.109, longitude: 17.033, source: "postal_code", label: "Wrocław" };
    const lookup = { status: "found", town: "Wrocław", postal_code: "51-515", location };

    const filled = withAddressLookup({ town: "wroclaw", postal_code: "", location: null }, lookup, { town: "wroclaw", postalCode: "" });
    const stale = withAddressLookup({ town: "Wrocław Psie Pole", postal_code: "", location: null }, lookup, { town: "wroclaw", postalCode: "" });
    const otherTown = withAddressLookup({ town: "Psie Pole", postal_code: "51-515", location: null }, { ...lookup, postal_code: null }, { town: "Psie Pole", postalCode: "51-515" });

    expect(filled).toEqual({ town: "Wrocław", postal_code: "51-515", location: { ...location, address: "51-515 Wrocław" } });
    expect(stale.location).toBeNull();
    expect(otherTown.town).toBe("Psie Pole");
  });

  it("lokalizacja wskazana ręcznie zostaje po sprawdzeniu tego samego adresu", () => {
    const manual = { latitude: 51.2, longitude: 17.2, source: "manual", address: "51-515 Wrocław" };
    const lookup = { status: "found", town: "Wrocław", location: { latitude: 51.1, longitude: 17.0, source: "postal_code" } };

    const base = withAddressLookup({ town: "Wrocław", postal_code: "51-515", location: manual }, lookup, { town: "Wrocław", postalCode: "51-515" });

    expect(base.location).toBe(manual);
  });

  it("niezapisane zmiany nie obejmują lokalizacji wyliczonej z adresu, ale obejmują wskazaną ręcznie", () => {
    const profile = filledProfile({ mode: "none" });
    const saved = profileSnapshot(profile);
    const previewed = { ...profile, base_info: { ...profile.base_info, location: { latitude: 51.1, longitude: 17.0, source: "postal_code" } } };
    const manual = { ...profile, base_info: { ...profile.base_info, location: { latitude: 51.1, longitude: 17.0, source: "manual" } } };

    expect(profileSnapshot(previewed)).toBe(saved);
    expect(profileSnapshot(manual)).not.toBe(saved);
  });
});
