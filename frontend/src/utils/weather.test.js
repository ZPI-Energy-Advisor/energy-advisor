import { describe, expect, it } from "vitest";
import { cloudLabel, hourlyWeather, quarterAt, weatherKind } from "./weather";

describe("weather", () => {
  it("kwadrans zawiera chwilę od początku do 15 minut", () => {
    const quarters = [{ start: "2026-11-13T10:00:00+01:00" }, { start: "2026-11-13T10:15:00+01:00" }];

    expect(quarterAt(quarters, "2026-11-13T09:14:59Z")).toBe(quarters[0]);
    expect(quarterAt(quarters, "2026-11-13T09:15:00Z")).toBe(quarters[1]);
    expect(quarterAt(quarters, "2026-11-13T09:30:00Z")).toBeNull();
  });

  it("ikona i opis z zachmurzenia, a noc bez słońca", () => {
    expect(weatherKind({ cloud_cover_pct: 10, ghi_w_m2: 300 })).toBe("sun");
    expect(weatherKind({ cloud_cover_pct: 40, ghi_w_m2: 300 })).toBe("partly");
    expect(weatherKind({ cloud_cover_pct: 10, ghi_w_m2: 0 })).toBe("night");
    expect(weatherKind({ cloud_cover_pct: 80, ghi_w_m2: 0 })).toBe("cloud");
    expect(weatherKind({ cloud_cover_pct: null })).toBeNull();
    expect([cloudLabel(0), cloudLabel(25), cloudLabel(70), cloudLabel(null)]).toEqual([
      "bezchmurnie", "częściowe zachmurzenie", "pochmurno", null,
    ]);
  });

  it("godziny doby to średnie z kwadransów, bez innych dób", () => {
    const quarters = [
      { start: "2026-11-13T10:00:00+01:00", temperature_c: 2, cloud_cover_pct: 20 },
      { start: "2026-11-13T10:45:00+01:00", temperature_c: 4, cloud_cover_pct: 60 },
      { start: "2026-11-14T00:00:00+01:00", temperature_c: -5, cloud_cover_pct: 0 },
    ];

    expect(hourlyWeather(quarters, "2026-11-13")).toEqual([{ hour: 10, cloud: 40, temperature: 3 }]);
    expect(hourlyWeather(null, "2026-11-13")).toEqual([]);
  });
});
