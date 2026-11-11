import { describe, expect, it } from "vitest";
import { createEmptyProfile, formatPostalCode, parseDecimal, parseSaveError, profileFromSaved, validateProfile } from "./profileForm";

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
            { loc: ["body", "pv_config", "net_metering", "power_of_pv_kwp"], msg: "Input should be less than or equal to 50", type: "less_than_equal" },
            { loc: ["body", "consumption_and_tariff", "tariff_type"], msg: "Operator PGE nie ma w cenniku taryfy G13.", type: "value_error" },
          ],
        },
      },
    };

    expect(parseSaveError(error)).toEqual({
      fields: {
        "base_info.postal_code": "Kod pocztowy w formacie 00-000.",
        "pv_config.power_of_pv_kwp": "Moc instalacji musi być większa niż 0 i najwyżej 50 kWp.",
        "consumption_and_tariff.tariff_type": "Operator PGE nie ma w cenniku taryfy G13.",
      },
      message: null,
    });
    expect(parseSaveError({ response: { data: { detail: "Coś poszło nie tak." } } })).toEqual({ fields: {}, message: "Coś poszło nie tak." });
    expect(parseSaveError({})).toEqual({ fields: {}, message: "Nie udało się zapisać profilu." });
  });
});
