import { describe, expect, it } from "vitest";
import { addMonths, daysBetween, monthWeeks, randomDay, rangeText } from "./dateRange";
import { daySummaries, fixedDevices } from "./historicalSchedule";

describe("dateRange", () => {
  it("układa miesiąc w tygodnie od poniedziałku", () => {
    const weeks = monthWeeks("2026-10");

    // 1 października 2026 to czwartek: trzy puste pola przed nim.
    expect(weeks[0]).toEqual([null, null, null, "2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04"]);
    expect(weeks.flat().filter(Boolean)).toHaveLength(31);
    expect(addMonths("2026-12", 1)).toBe("2027-01");
  });

  it("losuje dzień z zakresu włącznie i opisuje zakres", () => {
    expect(randomDay("2026-10-01", "2026-10-31", () => 0)).toBe("2026-10-01");
    expect(randomDay("2026-10-01", "2026-10-31", () => 0.999)).toBe("2026-10-31");
    expect(daysBetween("2026-10-25", "2026-10-26")).toBe(2); // także przez zmianę czasu
    expect(rangeText("2026-10-19", "2026-10-25")).toBe("19.10–25.10 (7 dni)");
  });
});

describe("historicalSchedule", () => {
  const action = (overrides) => ({
    device_id: "dev_wm", device_name: "Pralka", flexibility_mode: "shiftable", status: "moved", energy_kwh: 1,
    original_start: "2026-10-19T18:00:00+02:00", cost_before: 1.5, cost_after: 0.5, ...overrides,
  });

  it("liczy dni okresu tylko z urządzeń przesuwalnych", () => {
    const actions = [
      action(),
      action({ flexibility_mode: "fixed", device_id: "dev_fr", device_name: "Lodówka", status: "unchanged", cost_before: 9, cost_after: 9 }),
    ];

    expect(daySummaries(actions, "2026-10-19", "2026-10-20")).toEqual([
      { day: "2026-10-19", moved: 1, before: 1.5, after: 0.5, saving: 1 },
      { day: "2026-10-20", moved: 0, before: 0, after: 0, saving: 0 },
    ]);
    expect(fixedDevices(actions)).toEqual([{ deviceId: "dev_fr", name: "Lodówka", energy: 1 }]);
  });
});
