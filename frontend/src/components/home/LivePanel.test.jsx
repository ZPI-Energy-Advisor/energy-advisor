import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import LivePanel from "./LivePanel";

const LIVE = {
  until: "2026-10-12T14:10:00+02:00",
  indoor: [{
    device_id: "dev_hp_01", device_name: "Pompa ciepła", at: "2026-10-12T14:00:00+02:00",
    temp_c: 21.34, plan_c: 21.3, set_c: 21, band: [20, 22],
    points: [
      { start: "2026-10-12T00:00:00+02:00", plan_c: 21, temp_c: 21 },
      { start: "2026-10-12T00:15:00+02:00", plan_c: 20.9, temp_c: null },
    ],
  }],
  weather: { start: "2026-10-12T14:00:00+02:00", temperature_c: 6.4, cloud_cover_pct: 80, past: true },
  pv: {
    production_kwh: 4.2, self_kwh: 3.1, export_kwh: 1.1, export_pln: 0.55, planned_kwh: 6.5,
    hours: [{ start: "2026-10-12T13:00:00+02:00", planned_kwh: 1.2, actual_kwh: 1.1 }],
  },
  price_now: 0.876,
  export_price_now: 0.452,
  saving: { cost_before: 5.2, cost_after: 3.9, saving: 1.3, saving_percent: 25, excluded: [], planned_saving: 2.1 },
};

const panel = () => screen.getByRole("group", { name: "Na żywo" });

describe("LivePanel", () => {
  it("w czasie przebiegu pokazuje temperaturę w domu, pogodę, panele, cenę i oszczędność do teraz", () => {
    render(<LivePanel live={LIVE} />);

    const text = panel().textContent;
    expect(text).toContain("do 14:10");
    expect(text).toContain("W domu · Pompa ciepła21,3°C");
    expect(text).toContain("ustawiona 21°C, zakres 20–22°C · według planu 21,3°C · o 14:00");
    expect(within(panel()).getByRole("status", { name: "Pogoda teraz: 6°C, pochmurno" })).toBeTruthy();
    expect(text).toContain("pogoda z archiwum z planu");
    expect(text).toContain("Panele od początku planu4,20 kWh");
    expect(text).toContain("plan na dobę 6,50 kWh · w domu 3,10 kWh, do sieci 1,10 kWh · oddanie 0,55 zł");
    expect(text).toContain("urządzenia stałe są wyłączone, dopóki ich nie włączysz");
    expect(screen.getByLabelText("Temperatura w domu w dobie: Pompa ciepła")).toBeTruthy();
    expect(screen.getByLabelText("Produkcja paneli w godzinach: plan i symulacja")).toBeTruthy();
    expect(text).toContain("Plan na całą dobę: 2,10 zł. Plan przesuwa pracę w czasie");
    expect(text).toContain("Cena teraz0,88 zł/kWh");
    expect(text).toContain("oddanie 0,45 zł/kWh");
    expect(text).toContain("Oszczędność do teraz1,30 zł (25,0%)");
    expect(text).toContain("bez planu 5,20 zł, z planem 3,90 zł");
  });

  it("dom bez pompy i bez paneli nie ma tych kafli", () => {
    render(<LivePanel live={{ ...LIVE, indoor: [], pv: null, export_price_now: null, weather: null }} />);

    const text = panel().textContent;
    expect(text).not.toContain("W domu");
    expect(text).not.toContain("Panele");
    expect(text).not.toContain("Na dworze");
    expect(text).toContain("z sieci, w taryfie z planu");
  });

  it("temperatura poza zakresem i urządzenie z odchyleniem są opisane", () => {
    render(<LivePanel live={{
      ...LIVE,
      indoor: [{ ...LIVE.indoor[0], temp_c: 19.2 }],
      saving: { ...LIVE.saving, saving: -0.2, saving_percent: -3.8, excluded: [{ device_id: "dev_wm_01", device_name: "Pralka" }] },
    }} />);

    expect(screen.getByText("19,2°C").className).toContain("text-amber-700");
    expect(panel().textContent).toContain("bez Pralka (odchylenie od planu)");
  });

  it("bez przebiegu planu: pogoda doby, produkcja PV i podpowiedź", () => {
    render(<LivePanel weather={{ temperature_c: 3, cloud_cover_pct: 10, ghi_w_m2: 200 }} today={{ production_kwh: 2.5 }} />);

    const text = panel().textContent;
    expect(text).toContain("pogoda doby symulacji");
    expect(text).toContain("Panele w tej dobie2,50 kWh");
    expect(text).toContain("Uruchom plan na stronie „Plan na jutro”, żeby zobaczyć oszczędność");
    expect(text).not.toContain("Oszczędność do teraz");
  });
});
