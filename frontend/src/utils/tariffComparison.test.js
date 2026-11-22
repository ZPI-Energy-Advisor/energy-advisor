import { describe, expect, it } from "vitest";
import {
  CYCLE_COMPONENTS,
  CYCLE_GROUPS,
  chartKeysOf,
  chartTariffKeys,
  cycleGroupValue,
  detailsKey,
  formatDifference,
  formatPercent,
  keyLabel,
  profileEntry,
  tariffMatrix,
} from "./tariffComparison";
import { COMPARISON, PV_COMPARISON, chartRow, comparisonOf, entry } from "../test/tariffComparison";
import { formatPln } from "./tariffs";

describe("tariffComparison", () => {
  it("układa taryfy w macierz grupa × zwykła umowa / cena dynamiczna", () => {
    const rows = tariffMatrix(COMPARISON.tariffs);

    expect(rows.map((row) => [row.group, row.regular?.key ?? null, row.dynamic?.key ?? null])).toEqual([
      ["G11", "G11", "G11-dynamic"],
      ["G12", "G12", "G12-dynamic"],
      ["G13", "G13", null],
    ]);
  });

  it("dodaje grupę, która ma tylko ofertę dynamiczną", () => {
    const rows = tariffMatrix([entry("G11", 1), entry("G12-dynamic", 2)]);

    expect(rows.map((row) => [row.group, row.regular?.key ?? null, row.dynamic?.key ?? null])).toEqual([
      ["G11", "G11", null],
      ["G12", null, "G12-dynamic"],
    ]);
  });

  it("znajduje taryfę z profilu tylko przy uzupełnionym profilu", () => {
    expect(profileEntry(COMPARISON).key).toBe("G11");
    expect(profileEntry({ ...COMPARISON, from_profile: false })).toBeNull();
    expect(profileEntry({ ...COMPARISON, profile_tariff: "G12w" })).toBeNull();
  });

  it("formatuje procent po polsku", () => {
    expect(formatPercent(17.5)).toBe("17,5%");
    expect(formatPercent(null)).toBeNull();
  });

  it("wybiera do szczegółów taryfę klikniętą, a domyślnie z profilu albo najtańszą", () => {
    expect(detailsKey(COMPARISON, "G12")).toBe("G12");
    expect(detailsKey(COMPARISON, "G99")).toBe("G11");
    expect(detailsKey(comparisonOf([entry("G11", null, { is_profile: true }), entry("G12", 300)]), null)).toBe("G12");
    expect(detailsKey(null, null)).toBeNull();
  });

  it("rysuje domyślnie Twoją, najtańszą i zaznaczoną taryfę, a na żądanie wszystkie z cenami", () => {
    const keys = chartKeysOf([chartRow("00:00", { G11: 1, G12: 1, "G11-dynamic": 1, "G12-dynamic": 1 })]);

    expect(chartTariffKeys(COMPARISON, "G12", false, keys)).toEqual(["G11", "G12", "G12-dynamic"]);
    expect(chartTariffKeys(COMPARISON, null, true, keys)).toEqual(["G11", "G12", "G11-dynamic", "G12-dynamic"]);
  });

  it("„wszystkie” na wykresie to tylko taryfy z kwotą, a bez porównania każda taryfa z cenami", () => {
    const comparison = comparisonOf([entry("G11", 300, { is_profile: true }), entry("G11-dynamic", null)]);

    expect(chartTariffKeys(comparison, null, true, ["G11", "G11-dynamic"])).toEqual(["G11"]);
    expect(chartTariffKeys(null, null, false, ["G11", "G11-dynamic"])).toEqual(["G11", "G11-dynamic"]);
    expect(keyLabel("G12w-dynamic")).toBe("G12w z ceną dynamiczną");
    expect(keyLabel("G13")).toBe("G13");
  });

  it("dzieli okres na kolumny, które razem dają kwotę brutto", () => {
    const cycle = PV_COMPARISON.tariffs[0].cycles[0];
    const total = CYCLE_GROUPS.reduce((sum, group) => sum + cycleGroupValue(cycle, group), 0);

    expect(total).toBeCloseTo(cycle.net_total + cycle.vat, 2);
    expect(new Set(CYCLE_GROUPS.flatMap((group) => group.parts))).toEqual(new Set(CYCLE_COMPONENTS.map(([key]) => key)));
  });

  it("opisuje różnicę do taryfy odniesienia ze znakiem", () => {
    expect(formatDifference(12.5, formatPln)).toMatch(/^\+12,50 zł$/);
    expect(formatDifference(-3, formatPln)).toMatch(/^−3,00 zł$/);
    expect(formatDifference(0, formatPln)).toBe("tyle samo");
    expect(formatDifference(null, formatPln)).toBeNull();
  });
});
