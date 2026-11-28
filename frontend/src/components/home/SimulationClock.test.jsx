import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import SimulationClock from "./SimulationClock";

const CLOCK = { sim_time: "2026-10-13T10:05:00Z", running: false, speed: 60, stop_at: null };

describe("SimulationClock", () => {
  it("pokazuje pogodę doby symulacji przy zegarze", () => {
    render(
      <SimulationClock
        clock={CLOCK}
        onUpdate={() => true}
        weather={{ temperature_c: 11.6, cloud_cover_pct: 85, ghi_w_m2: 120, approximate: true }}
      />,
    );

    const badge = screen.getByRole("status", { name: "Pogoda w symulacji: 12°C, pochmurno" });
    expect(badge.getAttribute("title")).toMatch(/Pogoda dla regionu/);
  });

  it("w nocy bez chmur nie pokazuje słońca", () => {
    render(<SimulationClock clock={CLOCK} onUpdate={() => true} weather={{ temperature_c: 2, cloud_cover_pct: 5, ghi_w_m2: 0 }} />);

    expect(screen.getByRole("status", { name: "Pogoda w symulacji: 2°C, noc, bezchmurnie" })).toBeTruthy();
  });

  it("bez pogody nie ma plakietki", () => {
    render(<SimulationClock clock={CLOCK} onUpdate={() => true} />);

    expect(screen.queryByRole("status", { name: /Pogoda/ })).toBeNull();
  });
});
