import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import LiveIndicators from "./LiveIndicators";

const LIVE = {
  until: "2026-11-13T14:10:00+01:00",
  indoor: [{ device_id: "dev_hp_01", device_name: "Pompa ciepła", temp_c: 21.34, plan_c: 21.3, set_c: 21, band: [20, 22], points: [] }],
  weather: { start: "2026-11-13T14:00:00+01:00", temperature_c: 4.4, cloud_cover_pct: 90, past: false },
  pv: { production_kwh: 2.1, self_kwh: 1.6, export_kwh: 0.5, export_pln: 0.4, planned_kwh: 5.08, hours: [] },
  price_now: 0.61,
  export_price_now: null,
  saving: {
    cost_before: 2.57, cost_after: 3.0, saving: -0.43, saving_percent: -16.7, excluded: [],
    planned_saving: 7.53, progress_saving: 2.18,
  },
};

const item = (name) => screen.getByRole("listitem", { name });

describe("LiveIndicators", () => {
  it("w trakcie przebiegu pokazuje dom, pogodę, panele i oszczędność w miarę pracy, a nie ujemną różnicę kosztów", () => {
    render(<LiveIndicators live={LIVE} simTime="2026-11-13T13:10:00Z" />);

    expect(item(/^W domu \(Pompa ciepła\): 21,3°C/)).toBeTruthy();
    // Stały podpis zamiast opisu chmur, żeby ramka nie zmieniała szerokości.
    expect(item(/^Na dworze: 4°C/).textContent).toBe("4°Cna dworze");
    expect(item(/^Z paneli od początku planu: 2,10 kWh/)).toBeTruthy();
    const saving = item(/^Oszczędność do teraz/);
    expect(saving.textContent).toContain("2,18 zł");
    expect(saving.textContent).toContain("z 7,53 zł planu");
    expect(screen.queryByText(/-0,43/)).toBeNull();
  });

  it("dom bez pompy i bez paneli: tych wskaźników nie ma", () => {
    render(<LiveIndicators live={{ ...LIVE, indoor: [], pv: null }} simTime="2026-11-13T13:10:00Z" />);

    expect(screen.queryByRole("listitem", { name: /W domu/ })).toBeNull();
    expect(screen.queryByRole("listitem", { name: /Z paneli/ })).toBeNull();
    expect(item(/^Oszczędność do teraz/)).toBeTruthy();
  });

  it("bez przebiegu planu zostaje sama pogoda doby symulacji", () => {
    render(<LiveIndicators weather={{ temperature_c: 2, cloud_cover_pct: 5, ghi_w_m2: 300 }} simTime="2026-11-13T11:00:00Z" />);

    expect(screen.getAllByRole("listitem")).toHaveLength(1);
    expect(item(/^Na dworze: 2°C/)).toBeTruthy();
  });

  it("na przekroju domu dzieli się na dwie strony: w domu po lewej, na zewnątrz i wynik po prawej", () => {
    render(
      <>
        <LiveIndicators live={LIVE} simTime="2026-11-13T13:10:00Z" side="home" />
        <LiveIndicators live={LIVE} simTime="2026-11-13T13:10:00Z" side="outside" />
      </>,
    );

    const inside = screen.getByRole("list", { name: "Wskaźniki: w domu" });
    const outside = screen.getByRole("list", { name: "Wskaźniki: na zewnątrz i wynik planu" });
    expect(inside.className).toContain("left-0");
    expect(outside.className).toContain("right-0");
    expect(inside.textContent).toContain("21,3°C");
    expect(inside.textContent).not.toContain("z paneli");
    expect(outside.textContent).toContain("z paneli");
    expect(outside.textContent).toContain("2,18 zł");
    expect(outside.textContent).not.toContain("w domu");
  });

  it("bez żadnych danych nic nie pokazuje", () => {
    const { container } = render(<LiveIndicators simTime="2026-11-13T11:00:00Z" />);

    expect(container.textContent).toBe("");
  });
});
