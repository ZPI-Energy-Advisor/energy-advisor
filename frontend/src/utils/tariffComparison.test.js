import { describe, expect, it } from "vitest";
import {
  CYCLE_COMPONENTS,
  CYCLE_GROUPS,
  chartKeysOf,
  chartTariffKeys,
  comparisonSummary,
  cycleGroupValue,
  detailsKey,
  formatDifference,
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

  it("liczy oszczędność względem taryfy z profilu", () => {
    const { selected, cheapest, saving } = comparisonSummary(COMPARISON);

    expect([selected.key, cheapest.key, saving]).toEqual(["G11", "G12-dynamic", 70]);
  });

  it("nie liczy oszczędności, gdy taryfa z profilu nie ma kwoty", () => {
    const comparison = comparisonOf([entry("G11", null, { is_profile: true }), entry("G12", 300)]);

    expect(comparisonSummary(comparison)).toEqual({ selected: null, cheapest: comparison.tariffs[1], saving: null });
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
