import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import apiClient from "../api/client";
import PastDayPlanner from "./PastDayPlanner";

const RANGE = {
  first_day: "2024-08-24",
  last_day: "2026-11-11",
  file_periods: [{ first_day: "2026-10-01", last_day: "2026-10-30" }],
};

const PLAN = {
  id: "plan-past", plan_date: "2026-10-30", status: "draft", kind: "past_day", day_source: "files",
  created_at: "2026-11-12T10:00:00+01:00", approved_at: null,
  horizon_start: "2026-10-30T00:00:00+02:00", horizon_end: "2026-10-31T06:00:00+01:00",
  pricing: "PGE, G11", max_grid_kw: null, approximate_from: null, cost_before: 2, cost_after: 1.5, saving: 0.5,
  notes: ["Plan idealny na 30 października: pogoda i produkcja z paneli są z archiwum."], warnings: [], items: [], prices: [],
};

const renderPlanner = (props = {}) =>
  render(
    <MemoryRouter>
      <PastDayPlanner flatTariff={false} onEditSettings={() => {}} canRun {...props} />
    </MemoryRouter>,
  );

const mockGet = (plans = {}) =>
  vi.spyOn(apiClient, "get").mockImplementation((url, config) => {
    if (url === "/planning/past-days") return Promise.resolve({ data: RANGE });
    return Promise.resolve({ data: plans[config?.params?.date] ?? null });
  });

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-11-12T15:00:00"));
});
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("PastDayPlanner", () => {
  it("zaczyna od ostatniego dnia z plików i pokazuje zapisany plan idealny tego dnia", async () => {
    const get = mockGet({ "2026-10-30": PLAN });
    renderPlanner();

    expect(await screen.findByRole("heading", { name: "Plan idealny na piątek 30.10" })).toBeTruthy();
    expect(screen.getByLabelText("Dzień").value).toBe("2026-10-30");
    expect(get).toHaveBeenCalledWith("/planning/plans", { params: { date: "2026-10-30" } });
    expect(screen.getByText("Ten dzień jest w plikach urządzeń: „bez planu” to to, co dom naprawdę wtedy robił.")).toBeTruthy();
    expect(screen.getByText("Dni w plikach urządzeń: 01.10.2026–30.10.2026.")).toBeTruthy();
    expect(screen.getByText(/bez planu: tak, jak tego dnia w plikach urządzeń/)).toBeTruthy();
    // Plan dnia z przeszłości nie jest „nieaktualnym planem na jutro”.
    expect(screen.queryByText(/czyli nie na jutro/)).toBeNull();
    expect(screen.getByRole("button", { name: "Ułóż plan idealny ponownie" })).toBeTruthy();
  });

  it("układa plan idealny na wybrany dzień spoza plików", async () => {
    mockGet();
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({
      data: { ...PLAN, plan_date: "2026-05-14", day_source: "settings" },
    });
    renderPlanner();
    await screen.findByText(/Ten dzień jest w plikach/);

    fireEvent.change(screen.getByLabelText("Dzień"), { target: { value: "2026-05-14" } });
    expect(screen.getByText(/Tego dnia nie ma w plikach urządzeń/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Ułóż plan idealny" }));

    expect(await screen.findByRole("heading", { name: "Plan idealny na czwartek 14.05" })).toBeTruthy();
    expect(post).toHaveBeenCalledWith("/planning/plans", { plan_date: "2026-05-14" });
    expect(screen.getByText(/bez planu: z ustawień i historii/)).toBeTruthy();
  });

  it("dzień bez cen: komunikat z backendu zamiast planu", async () => {
    mockGet();
    vi.spyOn(apiClient, "post").mockRejectedValue({
      response: { status: 422, data: { detail: "Brak stawek Twojej taryfy na 01.01.2025." } },
    });
    renderPlanner();
    await screen.findByText(/Ten dzień jest w plikach/);

    fireEvent.click(screen.getByRole("button", { name: "Ułóż plan idealny" }));

    expect(await screen.findByText("Brak stawek Twojej taryfy na 01.01.2025.")).toBeTruthy();
    expect(screen.queryByRole("heading", { name: /Plan idealny na/ })).toBeNull();
  });

  it("dzień spoza zakresu cen nie da się ułożyć", async () => {
    mockGet();
    renderPlanner();
    await screen.findByText(/Ten dzień jest w plikach/);

    fireEvent.change(screen.getByLabelText("Dzień"), { target: { value: "2023-05-14" } });

    expect(screen.getByText(/Wybierz dzień od 24.08.2024 do 11.11.2026/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Ułóż plan idealny" }).disabled).toBe(true);
  });

  it("zatwierdzony plan idealny uruchamia się w symulacji", async () => {
    mockGet({ "2026-10-30": { ...PLAN, status: "approved", approved_at: "2026-11-12T10:05:00+01:00" } });
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({ data: {} });
    renderPlanner();

    fireEvent.click(await screen.findByRole("button", { name: /Uruchom symulację/ }));

    await waitFor(() => expect(post).toHaveBeenCalledWith("/home/plan-runs", { plan_id: "plan-past" }));
  });

  it("bez profilu mówi, co uzupełnić", async () => {
    vi.spyOn(apiClient, "get").mockRejectedValue({
      response: { status: 409, data: { detail: "Uzupełnij profil (operator i taryfa)." } },
    });
    renderPlanner();

    expect(await screen.findByText(/Uzupełnij profil/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Przejdź do profilu" })).toBeTruthy();
  });
});
