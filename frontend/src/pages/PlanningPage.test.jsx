import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import apiClient from "../api/client";
import PlanningPage from "./PlanningPage";

const WASHER = {
  device_id: "dev_wm_01",
  device_name: "Pralka Bosch",
  device_type: "washing_machine",
  device_category: "AGD",
  flexibility_mode: "shiftable",
  max_power_kw: null,
  programs: [{ program_id: "cotton_60", program_name: "Bawełna 60°C", duration_min: 120 }],
  default_windows: [{ start: "07:00", end: "22:00" }],
  is_ev: false,
  preference: {
    device_id: "dev_wm_01", enabled: false, program_id: null, windows: [{ start: "07:00", end: "22:00" }],
    energy_input: "kwh", energy_kwh: null, battery_kwh: null, current_percent: null, target_percent: null,
  },
  energy_needed_kwh: null,
};
const EV = {
  ...WASHER,
  device_id: "dev_ev_01",
  device_name: "Ładowarka EV",
  device_type: "ev_charger",
  device_category: "Pojazd elektryczny",
  flexibility_mode: "interruptible",
  max_power_kw: 3.7,
  programs: [],
  default_windows: [{ start: "18:00", end: "07:00" }],
  is_ev: true,
  preference: { ...WASHER.preference, device_id: "dev_ev_01", windows: [{ start: "18:00", end: "07:00" }] },
};
const BODY = { saved_at: null, charging_efficiency: 0.9, devices: [WASHER, EV] };

const renderPage = () => {
  const get = vi.spyOn(apiClient, "get").mockResolvedValue({ data: BODY });
  render(
    <MemoryRouter>
      <PlanningPage />
    </MemoryRouter>,
  );
  return get;
};

const card = (name) => screen.findByRole("region", { name });

afterEach(() => vi.restoreAllMocks());

describe("PlanningPage", () => {
  it("pobiera ustawienia zalogowanego użytkownika, bez domu Smart Home", async () => {
    const get = renderPage();

    await card("Pralka Bosch");
    expect(get).toHaveBeenCalledWith("/planning/preferences");
  });

  it("przy ładowarce pojemność baterii jest tylko przy poziomie baterii, a przedziały to czas podłączenia", async () => {
    renderPage();
    const ev = await card("Ładowarka EV");
    fireEvent.click(within(ev).getByRole("checkbox", { name: "Pracuje jutro" }));

    expect(within(ev).getByText("Kiedy auto jest podłączone")).toBeTruthy();
    expect(within(ev).queryByLabelText("Pojemność baterii")).toBeNull();
    fireEvent.click(within(ev).getByRole("radio", { name: "poziom baterii" }));
    expect(within(ev).getByLabelText("Pojemność baterii")).toBeTruthy();
  });

  it("pokazuje datę ostatniego zapisu", async () => {
    vi.spyOn(apiClient, "get").mockResolvedValue({ data: { ...BODY, saved_at: "2026-11-12T09:30:00Z" } });
    render(
      <MemoryRouter>
        <PlanningPage />
      </MemoryRouter>,
    );

    expect(await screen.findByText(/^Ostatnio zapisano: 12\.11/)).toBeTruthy();
  });

  it("domyślne przedziały pochodzą z pliku, a urządzenie może mieć kilka przedziałów", async () => {
    renderPage();
    const washer = await card("Pralka Bosch");
    fireEvent.click(within(washer).getByRole("checkbox", { name: "Pracuje jutro" }));

    expect(within(washer).getByRole("combobox").value).toBe("cotton_60");  // pierwszy program od razu
    expect(within(washer).getByLabelText("Pralka Bosch: od (przedział 1)").value).toBe("07:00");
    expect(within(washer).getByText("Godziny co 15 minut, np. 08:00, 08:15, 08:30.")).toBeTruthy();
    expect(within(washer).queryByRole("button", { name: /Przywróć z pliku/ })).toBeNull();
    fireEvent.click(within(washer).getByRole("button", { name: /Dodaj przedział/ }));
    // Nowy przedział zaczyna się tam, gdzie kończy się ostatni.
    expect(within(washer).getByLabelText("Pralka Bosch: od (przedział 2)").value).toBe("22:00");
    expect(within(washer).getByLabelText("Pralka Bosch: do (przedział 2)").value).toBe("00:00");
    expect(within(washer).getByRole("button", { name: /Przywróć z pliku \(07:00–22:00\)/ })).toBeTruthy();
    fireEvent.click(within(washer).getByRole("button", { name: "Usuń przedział 2: Pralka Bosch" }));
    expect(within(washer).queryByLabelText("Pralka Bosch: od (przedział 2)")).toBeNull();
  });

  it("blokuje zapis, gdy przedział jest krótszy niż program", async () => {
    renderPage();
    const put = vi.spyOn(apiClient, "put");
    const washer = await card("Pralka Bosch");
    fireEvent.click(within(washer).getByRole("checkbox", { name: "Pracuje jutro" }));
    fireEvent.change(within(washer).getByLabelText("Pralka Bosch: do (przedział 1)"), { target: { value: "08:00" } });

    fireEvent.click(screen.getByRole("button", { name: "Zapisz ustawienia" }));

    expect(put).not.toHaveBeenCalled();
    expect(within(washer).getByText("Najdłuższy przedział (1 h) jest krótszy niż program Bawełna 60°C (2 h).")).toBeTruthy();
  });

  it("zapisuje ustawienia z poziomem baterii auta", async () => {
    renderPage();
    const put = vi.spyOn(apiClient, "put").mockResolvedValue({ data: { ...BODY, saved_at: "2026-11-12T10:00:00Z" } });
    const ev = await card("Ładowarka EV");
    fireEvent.click(within(ev).getByRole("checkbox", { name: "Pracuje jutro" }));
    fireEvent.click(within(ev).getByRole("radio", { name: "poziom baterii" }));
    fireEvent.change(within(ev).getByLabelText("Pojemność baterii"), { target: { value: "60" } });
    fireEvent.change(within(ev).getByLabelText("Teraz w baterii"), { target: { value: "40" } });
    fireEvent.change(within(ev).getByLabelText("Naładuj do"), { target: { value: "70" } });
    expect(within(ev).getByText(/Z sieci auto pobierze ok\. 20,0 kWh/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Zapisz ustawienia" }));

    expect(await screen.findByText("Zapisano.")).toBeTruthy();
    expect(put.mock.calls[0][0]).toBe("/planning/preferences");
    const body = put.mock.calls[0][1];
    expect(body).not.toHaveProperty("mode");
    expect(body.devices[1]).toMatchObject({
      device_id: "dev_ev_01", enabled: true, energy_input: "percent", battery_kwh: 60, current_percent: 40, target_percent: 70,
      windows: [{ start: "18:00", end: "07:00" }],
    });
  });

  it("suszarka po pralce ma tylko godzinę końca, a pralka nie może wtedy czekać na suszarkę", async () => {
    const dryer = {
      ...WASHER,
      device_id: "dev_td_01",
      device_name: "Suszarka",
      device_type: "tumble_dryer",
      programs: [{ program_id: "dry", program_name: "Suszenie", duration_min: 90 }],
      preference: { ...WASHER.preference, device_id: "dev_td_01" },
    };
    vi.spyOn(apiClient, "get").mockResolvedValue({ data: { ...BODY, devices: [WASHER, dryer, EV] } });
    const put = vi.spyOn(apiClient, "put").mockResolvedValue({ data: { ...BODY, devices: [WASHER, dryer, EV] } });
    render(
      <MemoryRouter>
        <PlanningPage />
      </MemoryRouter>,
    );
    const dryerCard = await card("Suszarka");
    fireEvent.click(within(dryerCard).getByRole("checkbox", { name: "Pracuje jutro" }));
    const after = within(dryerCard).getAllByRole("combobox")[1];
    // Ładowarka nie ma programu, więc nie ma jej na liście.
    expect([...after.options].map((option) => option.textContent)).toEqual(["Nie czeka na inne urządzenie", "Pralka Bosch"]);
    fireEvent.change(after, { target: { value: "dev_wm_01" } });
    expect(within(dryerCard).getByText("Ruszy po końcu: Pralka Bosch, najwyżej 1 h później.")).toBeTruthy();
    // Start wyznacza pralka: zamiast przedziałów jest tylko „Skończ najpóźniej o”.
    expect(within(dryerCard).queryByText("Kiedy może pracować")).toBeNull();
    fireEvent.change(within(dryerCard).getByLabelText(/Skończ najpóźniej o/), { target: { value: "22:00" } });

    fireEvent.click(screen.getByRole("button", { name: "Zapisz ustawienia" }));
    expect(put).not.toHaveBeenCalled();
    expect(within(dryerCard).getByText("Pralka Bosch nie pracuje jutro. Zaznacz je albo usuń „Wykonaj po”.")).toBeTruthy();

    const washer = await card("Pralka Bosch");
    fireEvent.click(within(washer).getByRole("checkbox", { name: "Pracuje jutro" }));
    // Pralka nie dostaje wyboru „Wykonaj po”, bo jedyne inne urządzenie z programem już na nią czeka.
    expect(within(washer).getAllByRole("combobox")).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Zapisz ustawienia" }));

    expect(await screen.findByText("Zapisano.")).toBeTruthy();
    expect(put.mock.calls[0][1].devices[1]).toMatchObject({ device_id: "dev_td_01", after_device_id: "dev_wm_01", finish_by: "22:00" });
    expect(put.mock.calls[0][1].devices[0].after_device_id).toBeNull();
  });

  it("pokazuje błąd backendu przy właściwym urządzeniu", async () => {
    renderPage();
    vi.spyOn(apiClient, "put").mockRejectedValue({ response: { status: 422, data: { detail: [
      { loc: ["body", "devices", 0, "windows"], msg: "Przedziały godzin nachodzą na siebie.", type: "value_error" },
    ] } } });
    const washer = await card("Pralka Bosch");
    fireEvent.click(within(washer).getByRole("checkbox", { name: "Pracuje jutro" }));

    fireEvent.click(screen.getByRole("button", { name: "Zapisz ustawienia" }));

    expect(await within(washer).findByText("Przedziały godzin nachodzą na siebie.")).toBeTruthy();
  });
});
