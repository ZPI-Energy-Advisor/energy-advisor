import { describe, expect, it } from "vitest";
import {
  planBadges,
  deviceStateLabel,
  durationLabel,
  formatKw,
  formatPln,
  formatSimDate,
  formatSimTime,
  groupDevicesByCategory,
  isControllable,
  nearestSpeedStep,
  realDuration,
  speedLabel,
  periodLabel,
  planName,
} from "./home";

const device = (fields) => ({ device_name: "X", state: "off", power_kw: 0, programs: [], ...fields });

describe("home utils", () => {
  it("grupuje urządzenia po kategorii w stałej kolejności, a nieznane na końcu", () => {
    const groups = groupDevicesByCategory([
      device({ device_name: "Lampa", device_category: "Oświetlenie" }),
      device({ device_name: "Zmywarka", device_category: "AGD" }),
      device({ device_name: "Pralka", device_category: "AGD" }),
      device({ device_name: "Spoza rejestru", device_category: null }),
      device({ device_name: "PV", device_category: "OZE" }),
    ]);

    expect(groups.map((group) => group.category)).toEqual(["OZE", "AGD", "Oświetlenie", "Pozostałe"]);
    expect(groups[1].devices.map((item) => item.device_name)).toEqual(["Pralka", "Zmywarka"]);
  });

  it("opisuje stan urządzenia, w tym produkcję PV i program", () => {
    expect(deviceStateLabel(device({ state: "running", power_kw: -2.5 }))).toBe("Produkuje");
    expect(deviceStateLabel(device({ state: "running", power_kw: 1.8, program_id: "eco" }))).toBe("Program w toku");
    expect(deviceStateLabel(device({ state: "running", power_kw: 0.06 }))).toBe("Pracuje");
    expect(deviceStateLabel(device({ state: "unreachable", power_kw: null }))).toBe("Brak połączenia");
  });

  it("odróżnia przebieg planu od historii, a produkcja PV ma pierwszeństwo", () => {
    const planned = { ref: null, started_at: "2026-10-19T18:00:00+02:00", ends_at: "2026-10-19T19:00:00+02:00" };
    const history = { ...planned, ref: "act_1" };

    expect(deviceStateLabel(device({ state: "running", power_kw: 0.06, run: planned }))).toBe("Według planu");
    expect(deviceStateLabel(device({ state: "running", power_kw: 2.0, run: history }))).toBe("Jak w historii");
    expect(deviceStateLabel(device({ state: "running", power_kw: -2.5, run: history }))).toBe("Produkuje");
  });

  it("nie pozwala sterować urządzeniem bez połączenia albo po awarii", () => {
    expect(isControllable(device({ state: "idle" }))).toBe(true);
    expect(isControllable(device({ state: "unreachable" }))).toBe(false);
    expect(isControllable(device({ state: "error" }))).toBe(false);
  });

  it("pokazuje czas symulacji w strefie domu niezależnie od strefy przeglądarki", () => {
    const utcMidnight = "2026-10-24T22:00:00Z"; // północ 25.10 w Warszawie (jeszcze czas letni)

    expect(formatSimTime(utcMidnight)).toBe("00:00");
    expect(formatSimDate(utcMidnight)).toContain("25 października 2026");
  });

  it("formatuje liczby po polsku i bez minus zera", () => {
    expect(formatKw(1.8)).toBe("1,80 kW");
    expect(formatKw(-0)).toBe("0,00 kW");
    expect(formatKw(null)).toBe("—");
    expect(formatPln(3.7215)).toBe("3,72 zł");
  });

  it("tempo: próg suwaka, podpis i czas rzeczywisty", () => {
    expect(nearestSpeedStep(288)).toBe(4);
    expect(nearestSpeedStep(100)).toBe(3); // Tempo spoza progów: najbliższy próg (120).
    expect(nearestSpeedStep(null)).toBe(4);
    expect(speedLabel(1440)).toBe("doba w minutę");
    expect(speedLabel(144)).toBe("doba w 10 min");
    expect(speedLabel(3600)).toBe("doba w 24 s");
    expect(realDuration(40)).toBe("ok. 40 s");
    expect(realDuration(225)).toBe("ok. 4 min");
    expect(realDuration(4200)).toBe("ok. 1 h 10 min");
  });

  it("opisuje czas trwania programu", () => {
    expect(durationLabel(45)).toBe("45 min");
    expect(durationLabel(120)).toBe("2 h");
    expect(durationLabel(150)).toBe("2 h 30 min");
  });
});

describe("planBadges", () => {
  const action = (start, end, status = "scheduled") => ({ start, end, status });
  const run = (simTime, actions) => ({
    status: "running",
    sim_time: simTime,
    replayed_devices: [],
    devices: [{ device_id: "dev_wm_01", actions }],
  });
  const washer = [action("2026-10-19T13:00:00+02:00", "2026-10-19T15:00:00+02:00")];

  it("podaje godziny z planu i stan względem czasu symulacji", () => {
    expect(planBadges(run("2026-10-19T10:00:00+02:00", washer)).dev_wm_01).toEqual({
      text: "Plan 13:00–15:00 · czeka", tone: "neutral",
    });
    expect(planBadges(run("2026-10-19T14:00:00+02:00", washer)).dev_wm_01.text).toBe("Plan 13:00–15:00 · w trakcie");
    expect(planBadges(run("2026-10-19T15:00:00+02:00", washer)).dev_wm_01.text).toBe("Plan 13:00–15:00 · wykonane");
  });

  it("godziny i stan liczy z przyjętych akcji, bez odrzuconych", () => {
    const mixed = [
      action("2026-10-19T02:00:00+02:00", "2026-10-19T03:00:00+02:00"),
      action("2026-10-19T10:00:00+02:00", "2026-10-19T11:00:00+02:00", "rejected"),
    ];
    expect(planBadges(run("2026-10-19T10:30:00+02:00", mixed)).dev_wm_01.text).toBe("Plan 02:00–03:00 · wykonane");
  });

  it("po awarii albo ręcznym wyłączeniu plakietka mówi, że plan się nie wykonał", () => {
    const deviation = (kind) => ({ kind, device_id: "dev_wm_01" });
    const withCost = (deviations) => ({ ...run("2026-10-19T16:00:00+02:00", washer), cost: { deviations } });

    expect(planBadges(withCost([deviation("device_error")])).dev_wm_01).toEqual({
      text: "Plan 13:00–15:00 · awaria", tone: "error",
    });
    expect(planBadges(withCost([deviation("interrupted")])).dev_wm_01.text).toBe("Plan 13:00–15:00 · przerwane ręcznie");
    expect(planBadges(withCost([deviation("interrupted"), deviation("device_error")])).dev_wm_01.text).toContain("awaria");
    // Inne zużycie niż w planie nie przerywa planu.
    expect(planBadges(withCost([deviation("energy_mismatch")])).dev_wm_01.text).toBe("Plan 13:00–15:00 · wykonane");
    // Przebieg bez rachunku: awarie urządzeń.
    const withErrors = { ...run("2026-10-19T14:00:00+02:00", washer), errors: [{ device_id: "dev_wm_01" }] };
    expect(planBadges(withErrors).dev_wm_01.text).toBe("Plan 13:00–15:00 · awaria");
  });

  it("bez plakietek dla urządzeń z historii i bez akcji", () => {
    const withHistory = {
      ...run("2026-10-19T10:00:00+02:00", []),
      replayed_devices: [{ device_id: "dev_pv_01", history_day: "2026-10-12" }],
    };
    expect(planBadges(withHistory)).toEqual({});
  });

  it("odrzucona komenda i brak plakietek poza trwającym przebiegiem", () => {
    const rejected = [{ ...washer[0], status: "rejected" }];
    expect(planBadges(run("2026-10-19T10:00:00+02:00", rejected)).dev_wm_01.tone).toBe("error");
    expect(planBadges({ ...run("2026-10-19T10:00:00+02:00", washer), status: "completed" })).toEqual({});
    expect(planBadges(null)).toEqual({});
  });
});

describe("periodLabel", () => {
  it("w jednej dobie podaje dzień i godziny od–do", () => {
    expect(periodLabel({ day_start: "2026-11-19T00:00:00+01:00", until: "2026-11-19T19:00:00+01:00" })).toBe(
      "19 listopada, 00:00–19:00",
    );
  });

  it("przebieg planu przez północ podaje dzień przy obu końcach", () => {
    expect(periodLabel({ day_start: "2026-11-20T00:00:00+01:00", until: "2026-11-21T06:00:00+01:00" })).toBe(
      "20 listopada 00:00 – 21 listopada 06:00",
    );
  });

  it("dni tygodnia po „na” są w bierniku", async () => {
    const { forWeekdayDate } = await import("./dayPlan");
    expect(forWeekdayDate("2026-11-28")).toBe("sobotę 28.11");
    expect(forWeekdayDate("2026-11-25")).toBe("środę 25.11");
    expect(forWeekdayDate("2026-11-22")).toBe("niedzielę 22.11");
    expect(forWeekdayDate("2026-11-27")).toBe("piątek 27.11");
  });

  it("przebieg planu idealnego ma swoją nazwę", () => {
    expect(planName({ plan_date: "2026-05-14", plan_kind: "past_day" })).toBe("Plan idealny, 14 maja");
    expect(planName({ plan_date: "2026-11-13", plan_kind: "tomorrow" })).toBe("Plan na 13 listopada");
    expect(planName({ plan_date: "2026-11-13" })).toBe("Plan na 13 listopada");
  });
});
