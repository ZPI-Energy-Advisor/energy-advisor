import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import HomeDeviceList from "./HomeDeviceList";

const washer = (programs) => ({
  device_id: "dev_wm_01",
  device_name: "Pralka",
  device_type: "washing_machine",
  device_category: "AGD",
  flexibility_mode: "shiftable",
  programs,
  state: "off",
  program_id: null,
  power_kw: 0,
  energy_today_kwh: 0,
});
const COTTON = { program_id: "cotton_60", program_name: "Bawełna 60°C", duration_min: 120 };
const QUICK = { program_id: "quick_30", program_name: "Szybkie 30°C", duration_min: 30 };
const ECO = { program_id: "eco", program_name: "Eco", duration_min: 180 };

describe("HomeDeviceList", () => {
  it("po zmianie programów urządzenia nie wysyła programu, którego już nie ma", () => {
    const onCommand = vi.fn().mockResolvedValue(true);
    const { rerender } = render(<HomeDeviceList devices={[washer([COTTON, QUICK])]} onCommand={onCommand} />);
    fireEvent.change(screen.getByRole("combobox", { name: "Program: Pralka" }), { target: { value: "quick_30" } });

    rerender(<HomeDeviceList devices={[washer([ECO, COTTON])]} onCommand={onCommand} />);
    fireEvent.click(screen.getByRole("button", { name: "Uruchom program: Pralka" }));

    expect(screen.getByRole("combobox", { name: "Program: Pralka" }).value).toBe("eco");
    expect(onCommand).toHaveBeenCalledWith(expect.objectContaining({ device_id: "dev_wm_01" }), {
      command: "start_program",
      program_id: "eco",
    });
  });

  it("instalacja PV nie ma przycisków, a ładowarka EV ma", () => {
    const pv = { ...washer([]), device_id: "dev_pv_01", device_name: "Instalacja PV", device_type: "pv_inverter", device_category: "OZE" };
    const ev = { ...washer([]), device_id: "dev_ev_01", device_name: "Ładowarka EV", device_type: "ev_charger", device_category: "Pojazd elektryczny" };

    render(<HomeDeviceList devices={[pv, ev]} onCommand={vi.fn()} />);

    expect(screen.queryByRole("button", { name: /Instalacja PV/ })).toBeNull();
    expect(screen.getByRole("button", { name: "Włącz: Ładowarka EV" })).toBeTruthy();
  });

  it("blokuje sterowanie urządzeniem bez połączenia", () => {
    render(<HomeDeviceList devices={[{ ...washer([]), state: "unreachable", power_kw: null }]} onCommand={vi.fn()} />);

    expect(screen.getByRole("button", { name: "Włącz: Pralka" }).disabled).toBe(true);
    expect(screen.getByText("Brak połączenia")).toBeTruthy();
  });
});
