import { describe, expect, it } from "vitest";
import {
  CATEGORY_COLORS,
  DRILL_COLORS,
  PRODUCTION_KEY,
  REST_OF_HOUSE_KEY,
  UNAVAILABLE_NO_COMMON_DAYS,
  UNAVAILABLE_NO_DEVICE_FILES,
  breadcrumbs,
  buildChartRows,
  buildSeries,
  deviceUsageSource,
  profileAxis,
  ranking,
  totals,
  usageQuery,
} from "./deviceUsage";

const group = (key, kwh, cost, extra = {}) => ({
  key,
  label: extra.label ?? key,
  kwh,
  cost_pln: cost,
  total_kwh: kwh.reduce((a, b) => a + b, 0),
  total_cost_pln: cost.reduce((a, b) => a + b, 0),
  ...extra,
});

const response = (groups, extra = {}) => ({ groups, production: null, rest_of_house: null, ...extra });

describe("deviceUsageSource", () => {
  const range = { from: "2026-10-01", to: "2026-10-31" };

  it("plik urządzeń pokazuje własne urządzenia bez licznika", () => {
    expect(deviceUsageSource({ selectedFile: { id: "f1", source_type: "devices" }, dateRange: range })).toEqual({
      sourceId: "f1", meter: null, range,
    });
  });

  it("plik licznika bierze wszystkie pliki urządzeń z dni wspólnych", () => {
    const devicesAggregate = { data_start: "2026-10-10", data_end: "2026-11-15" };

    expect(
      deviceUsageSource({ selectedFile: { id: "m1", source_type: "meter" }, dateRange: range, devicesAggregate }),
    ).toEqual({ sourceId: "all-devices", meter: "m1", range: { from: "2026-10-10", to: "2026-10-31" } });
    expect(
      deviceUsageSource({ selectedFile: { id: "all", source_type: "meter" }, dateRange: range, devicesAggregate }).meter,
    ).toBe("all");
  });

  it("bez plików urządzeń albo wspólnych dni widok urządzeń jest niedostępny", () => {
    const meter = { id: "m1", source_type: "meter" };

    expect(deviceUsageSource({ selectedFile: meter, dateRange: range, devicesAggregate: null })).toEqual({
      unavailable: UNAVAILABLE_NO_DEVICE_FILES,
    });
    expect(
      deviceUsageSource({
        selectedFile: meter, dateRange: range, devicesAggregate: { data_start: "2026-06-01", data_end: "2026-06-30" },
      }),
    ).toEqual({ unavailable: UNAVAILABLE_NO_COMMON_DAYS });
  });
});

describe("drill-down", () => {
  const ev = { key: "Pojazd elektryczny", label: "Pojazd elektryczny" };
  const charger = { key: "ev_charger", label: "Ładowarka EV" };

  it("kolejne poziomy pytają API o kategorie, typy i urządzenia", () => {
    expect(usageQuery([])).toEqual({ group_by: "category" });
    expect(usageQuery([ev])).toEqual({ group_by: "type", category: "Pojazd elektryczny" });
    expect(usageQuery([ev, charger])).toEqual({ group_by: "instance", category: "Pojazd elektryczny", type: "ev_charger" });
    expect(usageQuery([ev], { flexibleOnly: true })).toEqual({ group_by: "type", category: "Pojazd elektryczny", flexible: true });
  });

  it("okruszki zaczynają się od wszystkich urządzeń", () => {
    expect(breadcrumbs([ev, charger]).map((crumb) => crumb.label)).toEqual([
      "Wszystkie", "Pojazd elektryczny", "Ładowarka EV",
    ]);
  });

  it("na poziomie urządzenia zostaje tylko ono i nie da się kliknąć dalej", () => {
    const data = response([group("dev_ev_01", [1], [1]), group("dev_ev_02", [2], [2])]);

    const series = buildSeries(data, [ev, charger, { key: "dev_ev_02", label: "Druga ładowarka" }]);

    expect(series.map((item) => [item.key, item.clickable])).toEqual([["dev_ev_02", false]]);
  });
});

describe("buildSeries", () => {
  it("kategorie mają stałe kolory, a reszta domu jest tylko w widoku wszystkich urządzeń", () => {
    const data = response([group("AGD", [1, 2], [1, 2])], {
      rest_of_house: { kwh: [3, 4], cost_pln: [3, 4], total_kwh: 7, total_cost_pln: 7, common_days: ["2026-10-01"] },
    });

    const all = buildSeries(data, []);
    const inCategory = buildSeries(data, [{ key: "AGD", label: "AGD" }]);

    expect(all.map((item) => [item.key, item.color])).toEqual([
      ["AGD", CATEGORY_COLORS.AGD],
      [REST_OF_HOUSE_KEY, "#cbd5e1"],
    ]);
    expect(inCategory.map((item) => item.key)).toEqual(["AGD"]);
    expect(inCategory[0].color).toBe(DRILL_COLORS[0]);
  });

  it("reszta domu bez wspólnych dni nie jest serią", () => {
    const data = response([group("AGD", [1], [1])], {
      rest_of_house: { kwh: [0], cost_pln: [0], total_kwh: 0, total_cost_pln: 0, common_days: [] },
    });

    expect(buildSeries(data, []).map((item) => item.key)).toEqual(["AGD"]);
  });
});

describe("profil doby", () => {
  it("dla godzin liczy średnią z dni, a dla dni zostawia kolejne doby", () => {
    const periods = ["2026-10-01T00:00:00+02:00", "2026-10-01T01:00:00+02:00", "2026-10-02T00:00:00+02:00", "2026-10-02T01:00:00+02:00"];
    const series = [{ key: "AGD", kwh: [1, 2, 3, 4], cost: [10, 20, 30, 40] }];

    const hourly = buildChartRows(periods, series, null, "1h");

    expect(hourly).toEqual([
      { label: "00:00", AGD__kwh: 2, AGD__pln: 20 },
      { label: "01:00", AGD__kwh: 3, AGD__pln: 30 },
    ]);
  });

  it("powtórzona godzina przy zmianie czasu trafia do tej samej pory dnia", () => {
    const axis = profileAxis(["2026-10-25T02:00:00+02:00", "2026-10-25T02:00:00+01:00", "2026-10-25T03:00:00+01:00"], "1h");

    expect(axis.labels).toEqual(["02:00", "03:00"]);
    expect(axis.positions).toEqual([0, 0, 1]);
    expect(axis.divisor).toBe(1);
  });

  it("produkcja PV idzie pod oś jako wartości ujemne", () => {
    const periods = ["2026-06-01T00:00:00+02:00", "2026-06-02T00:00:00+02:00"];

    const rows = buildChartRows(periods, [], { kwh: [5, 7], total_kwh: 12 }, "1d");

    expect(rows.map((row) => row[`${PRODUCTION_KEY}__kwh`])).toEqual([-5, -7]);
    expect(rows.map((row) => row.label)).toEqual(["2026-06-01", "2026-06-02"]);
  });
});

describe("ranking", () => {
  it("liczy udziały w zużyciu i koszcie od największego zużycia", () => {
    const series = buildSeries(response([group("AGD", [1], [3]), group("Ogrzewanie", [3], [1])]), []);

    expect(ranking(series).map((item) => [item.key, item.kwhShare, item.costShare])).toEqual([
      ["Ogrzewanie", 0.75, 0.25],
      ["AGD", 0.25, 0.75],
    ]);
    expect(totals(series)).toEqual({ kwh: 4, cost: 4, devices: 0 });
  });
});
