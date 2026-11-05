import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import apiClient from "../api/client";
import DeviceUsagePanel from "./DeviceUsagePanel";

const PERIODS = ["2026-10-01T00:00:00+02:00", "2026-10-02T00:00:00+02:00"];
const TARIFF = { name: "G11", source: "default", note: "Profil nie wskazuje taryfy, więc koszty są w taryfie G11." };

const group = (key, label, kwh, cost) => ({
  key, label, kwh, cost_pln: cost, total_kwh: kwh[0] + kwh[1], total_cost_pln: cost[0] + cost[1], devices_count: 1,
});

const RESPONSES = {
  category: {
    groups: [group("Pojazd elektryczny", "Pojazd elektryczny", [5, 5], [6, 6]), group("AGD", "AGD", [1, 1], [1, 1])],
    production: { kwh: [2, 3], total_kwh: 5 },
  },
  type: { groups: [group("ev_charger", "Ładowarka EV", [5, 5], [6, 6])], production: null },
  instance: {
    groups: [group("dev_ev_01", "Ładowarka w garażu", [3, 3], [4, 4]), group("dev_ev_02", "Ładowarka przy bramie", [2, 2], [2, 2])],
    production: null,
  },
};

const mockApi = (override) =>
  vi.spyOn(apiClient, "get").mockImplementation(async (url, { params }) => {
    if (override) return override(params);
    return { data: { ...RESPONSES[params.group_by], periods: PERIODS, tariff: TARIFF, rest_of_house: null, missing_price_slots: 0 } };
  });

const source = { sourceId: "file-1", meter: null, range: { from: "2026-10-01", to: "2026-10-02" } };

const renderPanel = (props = {}) =>
  render(<DeviceUsagePanel source={source} metric="kwh" resolution="1d" toolbar={null} {...props} />);

const lastParams = (get) => get.mock.calls.at(-1)[1].params;
const crumbs = () =>
  within(screen.getByRole("navigation", { name: "Poziom szczegółowości" }))
    .getAllByRole("listitem")
    .map((item) => item.textContent.replace("/", ""));
const legendButton = (name) => within(screen.getByRole("list", { name: "Legenda" })).getByRole("button", { name });

describe("DeviceUsagePanel", () => {
  it("pokazuje kategorie z sumą zużycia, kosztu i produkcji PV w okresie", async () => {
    const get = mockApi();
    renderPanel();

    expect(await screen.findByText("12,00 kWh")).toBeTruthy();
    expect(get).toHaveBeenCalledWith("/energy-files/file-1/devices/usage", {
      params: { group_by: "category", resolution: "1d", from: "2026-10-01", to: "2026-10-02" },
    });
    expect(screen.getByText("Koszt (taryfa G11)")).toBeTruthy();
    expect(screen.getByText("14,00 zł")).toBeTruthy();
    expect(screen.getByText(TARIFF.note)).toBeTruthy();
    expect(screen.getByText("Produkcja fotowoltaiki", { selector: "p" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Wstecz/ })).toBeNull();
    expect(screen.getByText(/10,00 kWh \(83,3%\)/)).toBeTruthy();
  });

  it("przy PV pokazuje pobór z sieci, autokonsumpcję, oddanie i oszczędność", async () => {
    mockApi();
    // Urządzenia zużyły 12 kWh za 14 zł, z sieci pobrano 7 kWh za 8 zł, a PV wyprodukowało 5 kWh.
    renderPanel({ gridImport: { kwh: 7, cost: 8, tariff: "G11" } });

    expect(await screen.findByText("Koszt zużycia urządzeń bez fotowoltaiki (taryfa G11)")).toBeTruthy();
    expect(screen.getByText("7,00 kWh (8,00 zł)")).toBeTruthy();
    expect(screen.getByText("Autokonsumpcja fotowoltaiki")).toBeTruthy();
    expect(screen.getByText("5,00 kWh", { selector: "p" })).toBeTruthy();
    expect(screen.getByText("Zaoszczędzone:").textContent).toBe("Zaoszczędzone: 6,00 zł");
    expect(screen.getByText("Produkcja fotowoltaiki:").textContent).toBe("Produkcja fotowoltaiki: 5,00 kWh");
    expect(screen.queryByText(/PV/)).toBeNull();
    expect(screen.queryByText(/obejmuje energię z/)).toBeNull();
  });

  it("bez wspólnej taryfy pokazuje autokonsumpcję w kWh zamiast oszczędności", async () => {
    mockApi();
    renderPanel({ gridImport: { kwh: 10, cost: 8, tariff: "G12" } });

    expect(await screen.findByText("Autokonsumpcja fotowoltaiki")).toBeTruthy();
    expect(screen.getByText("2,00 kWh", { selector: "p" })).toBeTruthy();
    expect(screen.queryByText("Zaoszczędzone:")).toBeNull();
  });

  it("kliknięcie kategorii zostawia tylko ją, a okruszki prowadzą z powrotem", async () => {
    const get = mockApi();
    renderPanel();

    fireEvent.click(await screen.findByRole("button", { name: "Pojazd elektryczny" }));
    await screen.findByRole("button", { name: "Ładowarka EV" });

    expect(lastParams(get)).toMatchObject({ group_by: "type", category: "Pojazd elektryczny" });
    expect(crumbs()).toEqual(["Wszystkie", "Pojazd elektryczny"]);
    expect(screen.getByText("Zużycie urządzeń: Pojazd elektryczny")).toBeTruthy();
    expect(screen.getByText("10,00 kWh")).toBeTruthy();
    expect(screen.queryByText("Produkcja fotowoltaiki", { selector: "p" })).toBeNull();

    fireEvent.click(legendButton("Ładowarka EV"));
    await screen.findByRole("button", { name: "Ładowarka w garażu" });

    expect(lastParams(get)).toMatchObject({ group_by: "instance", category: "Pojazd elektryczny", type: "ev_charger" });
    expect(crumbs()).toEqual(["Wszystkie", "Pojazd elektryczny", "Ładowarka EV"]);

    fireEvent.click(legendButton("Ładowarka w garażu"));
    await waitFor(() => expect(crumbs().at(-1)).toBe("Ładowarka w garażu"));
    expect(screen.getAllByText("6,00 kWh").length).toBeGreaterThan(0);
    expect(screen.queryByText("Ładowarka przy bramie")).toBeNull();
    expect(legendButton("Ładowarka w garażu").disabled).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: /Wstecz/ }));
    await waitFor(() => expect(crumbs()).toEqual(["Wszystkie", "Pojazd elektryczny", "Ładowarka EV"]));
    expect(legendButton("Ładowarka przy bramie")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Wszystkie" }));
    await screen.findByRole("button", { name: "AGD" });
    expect(lastParams(get)).toMatchObject({ group_by: "category" });
    expect(crumbs()).toEqual(["Wszystkie"]);
  });

  it("filtr urządzeń przesuwalnych pyta API tylko o nie", async () => {
    const get = mockApi();
    renderPanel();

    fireEvent.click(await screen.findByRole("button", { name: "Tylko przesuwalne" }));

    await waitFor(() => expect(lastParams(get)).toMatchObject({ group_by: "category", flexible: true }));
  });

  it("w trybie łączonym dodaje resztę domu i plik licznika w zapytaniu", async () => {
    const get = mockApi((params) => ({
      data: {
        ...RESPONSES.category,
        periods: PERIODS,
        tariff: TARIFF,
        missing_price_slots: 0,
        rest_of_house: {
          kwh: [4, 4], cost_pln: [3, 3], total_kwh: 8, total_cost_pln: 6, common_days: ["2026-10-01"], exceeded_days: ["2026-10-02"],
        },
        params,
      },
    }));
    renderPanel({ source: { ...source, sourceId: "all-devices", meter: "meter-1" } });

    expect(await screen.findByText(/Reszta domu/, { selector: "span" })).toBeTruthy();
    expect(lastParams(get)).toMatchObject({ meter: "meter-1" });
    expect(screen.getByText(/W 1 dniach urządzenia zużyły więcej/)).toBeTruthy();
    expect(screen.getByText("20,00 kWh")).toBeTruthy();
  });

  it("pokazuje błąd API i brak zużycia", async () => {
    vi.spyOn(apiClient, "get").mockRejectedValueOnce({ response: { data: { detail: "Nie znaleziono pliku." } } });
    const { unmount } = renderPanel();
    expect(await screen.findByText("Nie znaleziono pliku.")).toBeTruthy();
    unmount();

    mockApi(() => ({ data: { groups: [], production: null, rest_of_house: null, periods: PERIODS, tariff: TARIFF, missing_price_slots: 0 } }));
    renderPanel();
    expect(await screen.findByText("Brak zużycia urządzeń w wybranym okresie.")).toBeTruthy();
  });
});
