import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import HouseView from "./HouseView";

const base = {
  programs: [],
  program_id: null,
  program_ends_at: null,
  power_kw: 0,
  energy_today_kwh: 0,
  state: "off",
  flexibility_mode: "fixed",
};
const LIGHT = {
  ...base,
  device_id: "dev_light_01",
  device_name: "Oświetlenie salon",
  device_type: "light",
  device_category: "Oświetlenie",
  room: "living_room",
  state: "running",
  power_kw: 0.05,
};
const TV = {
  ...base,
  device_id: "dev_tv_01",
  device_name: "Telewizor",
  device_type: "tv",
  device_category: "RTV/IT",
  room: "living_room",
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
  state: "idle",
};
const POWER = { consumption_kw: 0.05, production_kw: 0, net_kw: 0.05 };

// Telefon: matchMedia zgłasza wąski ekran, więc HouseView pokazuje kafelki pokoi zamiast przekroju.
const asPhone = () =>
  vi.stubGlobal("matchMedia", (query) => ({
    matches: query === "(max-width: 767px)",
    media: query,
    addEventListener: () => {},
    removeEventListener: () => {},
  }));

const renderHouse = (onCommand = vi.fn().mockResolvedValue()) => {
  render(
    <HouseView
      devices={[LIGHT, TV, WASHER]}
      power={POWER}
      simTime="2026-10-19T19:00:00+02:00"
      onCommand={onCommand}
    />,
  );
  return onCommand;
};

describe("HouseView na telefonie: kafelki pokoi", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("pokazuje pokoje z urządzeniami zamiast przekroju", () => {
    asPhone();
    renderHouse();

    expect(screen.queryByRole("group", { name: "Przekrój domu" })).toBeNull();
    const salon = screen.getByRole("region", { name: "Salon" });
    expect(within(salon).getByRole("button", { name: /^Oświetlenie salon: / })).toBeTruthy();
    expect(within(salon).getByRole("button", { name: /^Telewizor: / })).toBeTruthy();
    expect(within(salon).getByText("światło włączone")).toBeTruthy();
    expect(screen.getByRole("region", { name: "Łazienka" })).toBeTruthy();
    // Pokoje bez urządzeń nie mają kafelka.
    expect(screen.queryByRole("region", { name: "Garaż" })).toBeNull();
  });

  it("stuknięcie w kafelek otwiera panel, w którym można wyłączyć światło i włączyć telewizor", () => {
    asPhone();
    const onCommand = renderHouse();

    fireEvent.click(screen.getByRole("button", { name: /^Oświetlenie salon: / }));
    expect(screen.getByRole("dialog", { name: "Oświetlenie salon" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Wyłącz: Oświetlenie salon" }));
    fireEvent.click(screen.getByRole("button", { name: /^Telewizor: / }));
    fireEvent.click(screen.getByRole("button", { name: "Włącz: Telewizor" }));

    expect(onCommand).toHaveBeenCalledWith(LIGHT, { command: "off" });
    expect(onCommand).toHaveBeenCalledWith(TV, { command: "on" });
  });

  it("uruchamia program pralki z panelu kafelka", () => {
    asPhone();
    const onCommand = renderHouse();

    fireEvent.click(screen.getByRole("button", { name: /^Pralka: / }));
    fireEvent.click(screen.getByRole("button", { name: "Uruchom program: Pralka" }));

    expect(onCommand).toHaveBeenCalledWith(WASHER, { command: "start_program", program_id: "cotton_60" });
  });

  it("na komputerze zostaje przekrój domu", () => {
    renderHouse();

    expect(screen.getByRole("group", { name: "Przekrój domu" })).toBeTruthy();
    expect(screen.queryByRole("region", { name: "Salon" })).toBeNull();
  });
});
