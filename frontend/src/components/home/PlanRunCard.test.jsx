import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import PlanRunCard from "./PlanRunCard";

const RUN = {
  id: "run-1",
  plan_id: "plan-1",
  plan_date: "2026-10-19",
  status: "completed",
  simulation_id: "sim_1",
  started_at: "2026-11-15T10:00:00Z",
  ended_at: "2026-11-15T10:06:00Z",
  sim_time: "2026-10-20T06:00:00+02:00",
  horizon_start: "2026-10-19T00:00:00+02:00",
  horizon_end: "2026-10-20T06:00:00+02:00",
  history_day: "2026-10-12",
  replay: { actions: 2, devices: 2, skipped_devices: [], rejected_actions: 0 },
  replayed_devices: [
    { device_id: "dev_pv_01", device_name: "Instalacja PV", history_day: "2026-10-12", history_kwh: -6.4, actual_kwh: -6.4 },
    { device_id: "dev_hp_01", device_name: "Pompa ciepła", history_day: "2026-10-12", history_kwh: 9.5, actual_kwh: 9.5 },
  ],
  planned_kwh: 6.4,
  actual_kwh: 1.4,
  devices: [
    {
      device_id: "dev_wm_01", device_name: "Pralka Bosch", kind: "program", planned_kwh: 1.4, actual_kwh: 1.4,
      actions: [{
        action_id: "dev_wm_01", device_id: "dev_wm_01", device_name: "Pralka Bosch", kind: "program",
        label: "Bawełna 60°C", start: "2026-10-19T11:45:00+02:00", end: "2026-10-19T12:30:00+02:00",
        energy_kwh: 1.4, status: "accepted", code: null, detail: null,
      }],
    },
    {
      device_id: "dev_ev_01", device_name: "Ładowarka EV", kind: "ev", planned_kwh: 5, actual_kwh: 0,
      actions: [{
        action_id: "dev_ev_01", device_id: "dev_ev_01", device_name: "Ładowarka EV", kind: "ev", label: "5 kWh",
        start: "2026-10-19T22:00:00+02:00", end: "2026-10-20T03:00:00+02:00", energy_kwh: 5,
        status: "rejected", code: "device_not_found", detail: "Nie ma urządzenia w rejestrze",
      }],
    },
  ],
  errors: [{
    device_id: "dev_lamp_01", device_name: "Lampa salon", sim_time: "2026-10-19T08:15:00+02:00",
    code: "device_unreachable", message: "Brak odpowiedzi urządzenia",
  }],
};

const COST = {
  complete: true,
  until: "2026-10-20T06:00:00+02:00",
  cost_before: 6.4,
  cost_after: 1.9,
  planned_cost: 1.78,
  saving: 4.5,
  saving_percent: 70.3,
  devices: [{
    device_id: "dev_wm_01", device_name: "Pralka Bosch", kind: "program", energy_before_kwh: 1.4,
    energy_after_kwh: 1.4, cost_before: 1.2, planned_cost: 0.4, cost_after: 0.42, saving: 0.78,
  }],
  excluded: [{ device_id: "dev_ev_01", device_name: "Ładowarka EV" }],
  pending: [],
  manual: [{ device_id: "dev_lamp_01", device_name: "Lampa salon", energy_kwh: 0.2, cost: 0.12 }],
  manual_cost: 0.12,
  pv: { production_kwh: 6.4, self_consumption_kwh: 3.1, plan_from_pv_kwh: 0.9, plan_kwh: 1.4 },
  deviations: [
    {
      kind: "rejected", device_id: "dev_ev_01", device_name: "Ładowarka EV", sim_time: "2026-10-19T22:00:00+02:00",
      end: null, message: "Hub nie przyjął komendy: Nie ma urządzenia w rejestrze.", excluded: true,
    },
    {
      kind: "grid_limit", device_id: null, device_name: null, sim_time: "2026-10-19T19:00:00+02:00",
      end: "2026-10-19T19:30:00+02:00", message: "Pobór z sieci do 4,40 kW, a limit przyłącza to 3,00 kW.",
      excluded: false,
    },
  ],
};

describe("PlanRunCard (raport przebiegu)", () => {
  it("na wierzchu ma koszt bez planu i z planem z okresem i opisem, resztę domu osobno, a szczegóły pod „Więcej”", () => {
    render(<PlanRunCard run={{ ...RUN, cost: COST }} />);

    const cost = screen.getByRole("region", { name: "Rachunek przed i po" });
    expect(cost.textContent).toContain("Bez planu6,40 zł");
    expect(cost.textContent).toContain("Z planem1,90 zł");
    expect(cost.textContent).toContain("według planu 1,78 zł");
    expect(cost.textContent).toContain("Oszczędność4,50 zł70,3% kosztu bez planu");
    expect(within(cost).queryByText("niepełny")).toBeNull();
    const row = within(cost).getByRole("row", { name: /Pralka Bosch/ });
    expect(row.textContent).toContain("1,20 zł");
    expect(row.textContent).toContain("0,78 zł");
    expect(within(cost).getByRole("heading", { name: "Koszt zaplanowanych urządzeń" })).toBeTruthy();
    expect(cost.textContent).toContain("19 października 00:00 – 20 października 06:00");
    expect(cost.textContent).toContain("Liczymy tylko te urządzenia");
    const facts = cost.querySelector("dl");
    expect(facts.textContent).toContain("Poza porównaniemŁadowarka EV");
    expect(facts.textContent).toContain("Odchylenia2");
    // Ręczne włączenia i PV osobno, z dopiskiem, że nie zmieniają oszczędności.
    const rest = within(cost).getByRole("group", { name: "Reszta domu" });
    expect(rest.textContent).toContain("nie wchodzi do oszczędności");
    expect(rest.textContent).toContain("Włączone ręcznie0,12 zł");
    expect(rest.textContent).toContain("PV6,40 kWh, z tego plan 0,90 kWh");
    expect(facts.textContent).not.toContain("Włączone ręcznie");
    const more = [...cost.querySelectorAll("details")].find((item) => item.querySelector("summary").textContent === "Więcej");
    expect(more.textContent).toContain("Włączone ręcznie: Lampa salon 0,20 kWh (0,12 zł).");
    expect(more.textContent).toContain(
      "PV wyprodukowało 6,40 kWh. Od razu w domu zużyto 3,10 kWh, z czego 0,90 kWh wzięły urządzenia z planu (64% ich zużycia).",
    );
    const deviations = within(cost).getByRole("list", { name: "Odchylenia od planu", hidden: true });
    expect(deviations.textContent).toContain(
      "22:00 Odrzucona komenda – Ładowarka EV: Hub nie przyjął komendy: Nie ma urządzenia w rejestrze. (poza porównaniem)",
    );
    expect(deviations.textContent).toContain("19:00–19:30 Limit przyłącza: Pobór z sieci do 4,40 kW");
    // Awarie są wśród odchyleń, więc nie ma osobnego alertu.
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("nie powtarza kosztu według planu, gdy zgadza się ze zmierzonym", () => {
    render(<PlanRunCard run={{ ...RUN, cost: { ...COST, cost_after: 9.4, planned_cost: 9.4 } }} />);

    const cost = screen.getByRole("region", { name: "Rachunek przed i po" });
    expect(cost.textContent).toContain("Z planem9,40 zł");
    expect(cost.textContent).not.toContain("według planu");
  });

  it("raport po „Zakończ” ma plakietkę „niepełny” z godziną w podpowiedzi, a okres do chwili zakończenia", () => {
    render(<PlanRunCard run={{ ...RUN, status: "ended", cost: {
      ...COST, complete: false, until: "2026-10-19T14:00:00+02:00", excluded: [],
      pending: [{ device_id: "dev_ev_01", device_name: "Ładowarka EV" }],
    } }} />);

    const cost = screen.getByRole("region", { name: "Rachunek przed i po" });
    const badge = within(cost).getByText("niepełny");
    expect(badge.getAttribute("title")).toBe("Porównane są urządzenia, które skończyły pracę do 14:00.");
    expect(cost.textContent).toContain("Nie skończyły pracyŁadowarka EV");
    // Okres kończy się chwilą „Zakończ”, nie końcem planu o 06:00.
    expect(cost.textContent).toContain("19 października, 00:00–14:00");
    expect(cost.textContent).not.toContain("06:00");
  });

  it("energia urządzeń z planu i z historii jest pod „Energia urządzeń”", () => {
    render(<PlanRunCard run={{ ...RUN, cost: COST }} />);

    const energy = screen.getByText(/Energia urządzeń: 1,40 kWh z 6,40 kWh według planu/).closest("details");
    expect(energy.open).toBe(false);
    const ev = within(energy).getByRole("listitem", { name: "Ładowarka EV", hidden: true });
    expect(ev.textContent).toContain("Odrzucone: Nie ma urządzenia w rejestrze");
    const history = within(energy).getByRole("region", { name: "Z dnia referencyjnego", hidden: true });
    expect(history.textContent).toContain("Pracują same, tak jak 12 października 2026:");
    expect(history.textContent).toContain("Instalacja PV: 6,40 kWh z 6,40 kWh produkcji");
  });

  it("podaje dzień przy urządzeniu, gdy urządzenia mają różne dni referencyjne, i nie pokazuje -0", () => {
    const [pv, heatPump] = RUN.replayed_devices;
    render(<PlanRunCard run={{ ...RUN, replayed_devices: [
      { ...pv, history_day: "2026-10-18", actual_kwh: -0 },
      heatPump,
    ] }} />);

    const history = screen.getByRole("region", { name: "Z dnia referencyjnego" });
    expect(history.textContent).toContain("Pracują same, tak jak w dniu referencyjnym:");
    expect(history.textContent).toContain("Instalacja PV (jak 18 października 2026): 0,00 kWh z 6,40 kWh produkcji");
    expect(history.textContent).toContain("Pompa ciepła (jak 12 października 2026)");
    expect(history.textContent).not.toContain("-0,00");
  });

  it("PV z prognozy i pompa dopasowana do pogody mówią, skąd jest ich doba", () => {
    const [pv, heatPump] = RUN.replayed_devices;
    render(<PlanRunCard run={{ ...RUN, replayed_devices: [
      { ...pv, source: "forecast", history_kwh: -8.2, actual_kwh: -2.1, reference_kwh: -6.4 },
      { ...heatPump, source: "forecast", history_kwh: 14.5, actual_kwh: 3.2, reference_kwh: 9.5 },
    ] }} />);

    const history = screen.getByRole("region", { name: "Z dnia referencyjnego" });
    expect(history.textContent).toContain("Pracują same:");
    expect(history.textContent).toContain("Instalacja PV (z prognozy pogody): 2,10 kWh z 8,20 kWh produkcji");
    expect(history.textContent).toContain(
      "Pompa ciepła (dopasowana do pogody, godziny jak 12 października 2026): 3,20 kWh z 14,50 kWh",
    );
  });

  it("przebieg w trakcie pokazuje postęp i odchylenia zamiast rachunku", () => {
    render(<PlanRunCard run={{ ...RUN, status: "running", actual_kwh: 0.6, cost: { ...COST, complete: false } }} />);

    expect(screen.queryByRole("region", { name: "Rachunek przed i po" })).toBeNull();
    expect(screen.getByText(/Plan trwa: urządzenia z planu zużyły 0,60 kWh z 6,40 kWh/)).toBeTruthy();
    expect(screen.getByRole("alert").textContent).toContain("19:00–19:30 Limit przyłącza");
  });

  it("przebieg sprzed rachunku pokazuje awarie urządzeń", () => {
    render(<PlanRunCard run={RUN} />);

    expect(screen.getByRole("alert").textContent).toContain("08:15 Lampa salon: Brak odpowiedzi urządzenia");
  });
});
