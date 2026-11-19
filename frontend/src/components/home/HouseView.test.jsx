import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import HouseView from "./HouseView";

const SIM_TIME = "2026-10-19T19:00:00+02:00";
const POWER = { consumption_kw: 2.5, production_kw: 0, net_kw: 2.5 };

const base = {
  programs: [],
  program_id: null,
  program_ends_at: null,
  power_kw: 0,
  energy_today_kwh: 0,
  state: "off",
};
const KETTLE = {
  ...base,
  device_id: "dev_kt_01",
  device_name: "Czajnik",
  device_type: "kettle",
  device_category: "AGD",
  room: "kitchen",
  flexibility_mode: "fixed",
};
const WASHER = {
  ...base,
  device_id: "dev_wm_01",
  device_name: "Pralka",
  device_type: "washing_machine",
  device_category: "AGD",
  room: "bathroom",
  flexibility_mode: "shiftable",
  programs: [{ program_id: "cotton_60", program_name: "Bawełna 60°C", duration_min: 120 }],
  state: "running",
  program_id: "cotton_60",
  program_ends_at: "2026-10-19T20:00:00+02:00",
  power_kw: 1.8,
  energy_today_kwh: 0.9,
};
const PV = {
  ...base,
  device_id: "dev_pv_01",
  device_name: "Instalacja PV",
  device_type: "pv_inverter",
  device_category: "OZE",
  room: "roof",
  flexibility_mode: "fixed",
  state: "running",
  power_kw: -3,
  energy_today_kwh: -9,
};
const EV = {
  ...base,
  device_id: "dev_ev_01",
  device_name: "Ładowarka EV",
  device_type: "ev_charger",
  device_category: "Pojazd elektryczny",
  room: "garage",
  flexibility_mode: "interruptible",
  state: "running",
  power_kw: 3.7,
  run: { ref: null, started_at: "2026-10-19T18:00:00+02:00", ends_at: "2026-10-19T22:00:00+02:00" },
};

const renderHouse = (devices, { onCommand = vi.fn().mockResolvedValue(true), power = POWER } = {}) => {
  const view = render(<HouseView devices={devices} power={power} simTime={SIM_TIME} onCommand={onCommand} />);
  return { ...view, onCommand };
};

describe("HouseView", () => {
  it("pokazuje urządzenia w pomieszczeniach ze stanem w tekście i licznik poboru z sieci", () => {
    renderHouse([KETTLE, WASHER, { ...KETTLE, device_id: "dev_x", device_name: "Lampa ogród", room: null, state: "error" }]);

    const kitchen = screen.getByRole("group", { name: "Kuchnia" });
    expect(within(kitchen).getByRole("button", { name: "Czajnik: Wyłączone" })).toBeTruthy();
    const bathroom = screen.getByRole("group", { name: "Łazienka" });
    expect(within(bathroom).getByRole("button", { name: "Pralka: Program w toku, 1,80 kW" })).toBeTruthy();
    const other = screen.getByRole("group", { name: "Inne" });
    const broken = within(other).getByRole("button", { name: "Lampa ogród: Awaria" });
    expect(broken.dataset.tone).toBe("error");
    expect(screen.getByRole("img", { name: "Licznik: Pobór z sieci 2,50 kW" })).toBeTruthy();
  });

  it("dymek urządzenia stałego ma moc, energię i przycisk Włącz", () => {
    const { onCommand } = renderHouse([KETTLE]);

    fireEvent.click(screen.getByRole("button", { name: "Czajnik: Wyłączone" }));
    const popover = screen.getByRole("dialog", { name: "Czajnik" });
    expect(popover.textContent).toContain("Czajnik · Kuchnia");
    expect(popover.textContent).toContain("0,00 kW");
    fireEvent.click(within(popover).getByRole("button", { name: "Włącz: Czajnik" }));

    expect(onCommand).toHaveBeenCalledWith(expect.objectContaining({ device_id: "dev_kt_01" }), { command: "on" });
  });

  it("pracujące urządzenie stałe wyłącza się z dymku, a polecenie w toku blokuje przycisk", async () => {
    let resolve;
    const onCommand = vi.fn(() => new Promise((done) => (resolve = done)));
    renderHouse([{ ...KETTLE, state: "running", power_kw: 2.2 }], { onCommand });

    fireEvent.click(screen.getByRole("button", { name: "Czajnik: Pracuje, 2,20 kW" }));
    const off = screen.getByRole("button", { name: "Wyłącz: Czajnik" });
    fireEvent.click(off);

    expect(onCommand).toHaveBeenCalledWith(expect.objectContaining({ device_id: "dev_kt_01" }), { command: "off" });
    expect(off.disabled).toBe(true);
    resolve(true);
    await waitFor(() => expect(screen.getByRole("button", { name: "Wyłącz: Czajnik" }).disabled).toBe(false));
  });

  it("dymek urządzenia przesuwalnego pokazuje program bez przycisków włącz i wyłącz", () => {
    renderHouse([WASHER]);

    fireEvent.click(screen.getByRole("button", { name: /^Pralka:/ }));
    const popover = screen.getByRole("dialog", { name: "Pralka" });
    expect(popover.textContent).toContain("Program: Bawełna 60°C, koniec 20:00");
    expect(popover.textContent).toContain("0,90 kWh");
    expect(popover.textContent).toContain("w widoku „Lista”");
    expect(within(popover).queryByRole("button", { name: /Włącz|Wyłącz/ })).toBeNull();
  });

  it("instalacja PV pokazuje produkcję bez sterowania", () => {
    renderHouse([PV], { power: { consumption_kw: 0, production_kw: 3, net_kw: -3 } });

    const pv = within(screen.getByRole("group", { name: "Dach" })).getByRole("button", { name: "Instalacja PV: Produkuje, 3,00 kW" });
    fireEvent.click(pv);
    const popover = screen.getByRole("dialog", { name: "Instalacja PV" });
    expect(within(popover).getByText("Produkcja")).toBeTruthy();
    expect(popover.textContent).toContain("3,00 kW");
    expect(popover.textContent).toContain("9,00 kWh");
    expect(within(popover).queryByRole("button", { name: /Włącz|Wyłącz/ })).toBeNull();
    expect(screen.getByRole("img", { name: "Licznik: Oddawanie do sieci 3,00 kW" })).toBeTruthy();
  });

  it("ładowarka według planu ma oznaczenie i postęp sesji", () => {
    renderHouse([EV]);

    const ev = within(screen.getByRole("group", { name: "Garaż" })).getByRole("button", { name: "Ładowarka EV: Według planu, 3,70 kW" });
    fireEvent.click(ev);
    const popover = screen.getByRole("dialog", { name: "Ładowarka EV" });
    expect(popover.textContent).toContain("Według planu, koniec 22:00");
    expect(popover.textContent).toContain("Sesja ładowania: 25% czasu");
  });

  it("dymek czyta urządzenie przy każdym odświeżeniu stanu i zamyka się klawiszem Escape", () => {
    const { rerender, onCommand } = renderHouse([KETTLE]);
    fireEvent.click(screen.getByRole("button", { name: "Czajnik: Wyłączone" }));

    rerender(<HouseView devices={[{ ...KETTLE, state: "running", power_kw: 2.2 }]} power={POWER} simTime={SIM_TIME} onCommand={onCommand} />);
    expect(within(screen.getByRole("dialog", { name: "Czajnik" })).getByRole("button", { name: "Wyłącz: Czajnik" })).toBeTruthy();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("blokuje sterowanie z dymku przy awarii urządzenia", () => {
    renderHouse([{ ...KETTLE, state: "unreachable", power_kw: null }]);

    fireEvent.click(screen.getByRole("button", { name: "Czajnik: Brak połączenia" }));
    expect(screen.getByRole("button", { name: "Włącz: Czajnik" }).disabled).toBe(true);
  });

  it("bez urządzeń prosi o import pliku", () => {
    renderHouse([]);

    expect(screen.getByRole("region", { name: "Dom" }).textContent).toContain("Zaimportuj plik urządzeń");
  });
});
