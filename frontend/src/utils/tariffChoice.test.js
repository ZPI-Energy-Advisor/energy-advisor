import { describe, expect, it } from "vitest";
import { dynamicAllowed, flatTariffNote, profileChoice, sameChoice } from "./tariffChoice";

describe("flatTariffNote", () => {
  it("G11 bez PV: oszczędność 0 z podpowiedzią taryfy dynamicznej", () => {
    const note = flatTariffNote({ tariff_group: "G11", tariff_dynamic: false, prosumer: false });

    expect(note).toMatch(/kosztuje tyle samo o każdej porze/);
    expect(note).toMatch(/0 zł/);
    expect(note).toMatch(/ceną dynamiczną/);
  });

  it("G11 z PV: zysk tylko z godzin produkcji paneli", () => {
    expect(flatTariffNote({ tariff_group: "G11", tariff_dynamic: false, prosumer: true })).toMatch(/panele produkują/);
  });

  it("inne taryfy i G11 z ceną dynamiczną nie mają uwagi", () => {
    expect(flatTariffNote({ tariff_group: "G12", tariff_dynamic: false })).toBeNull();
    expect(flatTariffNote({ tariff_group: "G11", tariff_dynamic: true })).toBeNull();
    expect(flatTariffNote(null)).toBeNull();
  });
});

describe("wybór taryfy", () => {
  it("taryfa z profilu i porównanie wyborów", () => {
    const choice = profileChoice({ consumption_and_tariff: { tariff_type: "G12", dynamic_price: true } });

    expect(choice).toEqual({ group: "G12", dynamic: true });
    expect(sameChoice(choice, { group: "G12", dynamic: true })).toBe(true);
    expect(sameChoice(choice, { group: "G12", dynamic: false })).toBe(false);
    expect(profileChoice({ consumption_and_tariff: {} })).toBeNull();
  });

  it("cena dynamiczna tylko z grupami dopuszczonymi przez sprzedawcę", () => {
    const options = { dynamic_offer: { distribution_groups: ["G11", "G12"] } };

    expect(dynamicAllowed(options, "G12")).toBe(true);
    expect(dynamicAllowed(options, "G13")).toBe(false);
    expect(dynamicAllowed({ dynamic_offer: null }, "G11")).toBe(false);
  });
});
