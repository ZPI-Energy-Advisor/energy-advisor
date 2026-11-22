import { act, render, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import apiClient from "../api/client";
import { EnergyFileProvider } from "./EnergyFileProvider";
import { useEnergyFiles } from "../hooks/useEnergyFiles";
import { CurrentUserContext } from "./currentUserContext";
import { loginAs } from "../test/auth";

const FILE = { id: "f1", file_name: "dom.csv", status: "completed", data_start: "2026-01-01", data_end: "2026-03-31" };

const dataFor = (from = FILE.data_start, to = FILE.data_end, allTariffs = false) => ({
  file: FILE,
  date_from: from,
  date_to: to,
  results: { pricing: { all_tariffs: allTariffs }, statistics: { days_analyzed: 1 } },
});

const mockApi = () =>
  vi.spyOn(apiClient, "get").mockImplementation(async (url, { params } = {}) => {
    if (url === "/energy-files") return { data: { items: [FILE], total: 1, page: 1, total_pages: 1 } };
    return { data: dataFor(params?.from, params?.to, params?.tariffs === "all") };
  });

const renderProvider = () => {
  const context = {};
  function Probe() {
    Object.assign(context, useEnergyFiles());
    return null;
  }
  const tree = (version) => (
    <CurrentUserContext.Provider value={{ version }}>
      <EnergyFileProvider>
        <Probe />
      </EnergyFileProvider>
    </CurrentUserContext.Provider>
  );
  const { rerender } = render(tree(1));
  context.setUserVersion = (version) => rerender(tree(version));
  return context;
};

const dataCalls = (get) => get.mock.calls.filter(([url]) => url.endsWith("/data"));

describe("EnergyFileProvider", () => {
  it("powrót do wcześniejszego zakresu bierze dane z pamięci podręcznej", async () => {
    loginAs();
    const get = mockApi();
    const context = renderProvider();
    await waitFor(() => expect(context.selectedFileId).toBe("f1"));

    await act(() => context.applyDateRange({ from: "2026-02-01", to: "2026-02-28" }));
    expect(context.viewSource).toEqual({ fileId: "f1", range: { from: "2026-02-01", to: "2026-02-28" } });
    await act(() => context.applyDateRange({ from: FILE.data_start, to: FILE.data_end }));

    expect(dataCalls(get).map(([, { params }]) => params)).toEqual([
      { tariffs: "profile" },
      { from: "2026-02-01", to: "2026-02-28", tariffs: "profile" },
    ]);
    expect(context.dateRange).toEqual({ from: FILE.data_start, to: FILE.data_end });
    expect(context.viewSource).toEqual({ fileId: "f1", range: null });
  });

  it("każdy ekran dostaje dane w swoim trybie: Analiza ceny wszystkich taryf, Dashboard rachunek z profilu", async () => {
    loginAs();
    const get = mockApi();
    const context = renderProvider();
    await waitFor(() => expect(context.selectedFileId).toBe("f1"));

    act(() => context.requireAllTariffs(true));
    await waitFor(() => expect(context.results.pricing.all_tariffs).toBe(true));
    act(() => context.requireAllTariffs(false));
    await waitFor(() => expect(context.results.pricing.all_tariffs).toBe(false));
    act(() => context.requireAllTariffs(true));
    await waitFor(() => expect(context.results.pricing.all_tariffs).toBe(true));

    expect(dataCalls(get).map(([, { params }]) => params.tariffs)).toEqual(["profile", "all"]);
  });

  it("wejście na Analizę w trakcie zmiany zakresu nie gubi nowego zakresu", async () => {
    loginAs();
    let release;
    const get = mockApi();
    const context = renderProvider();
    await waitFor(() => expect(context.selectedFileId).toBe("f1"));
    get.mockImplementationOnce(
      (url, { params }) => new Promise((resolve) => (release = () => resolve({ data: dataFor(params.from, params.to) }))),
    );

    let applied;
    act(() => {
      applied = context.applyDateRange({ from: "2026-02-01", to: "2026-02-28" });
    });
    act(() => context.requireAllTariffs(true));
    await act(async () => {
      release();
      await applied;
    });

    await waitFor(() => expect(context.results.pricing.all_tariffs).toBe(true));
    expect(context.dateRange).toEqual({ from: "2026-02-01", to: "2026-02-28" });
    expect(dataCalls(get).at(-1)[1].params).toEqual({ from: "2026-02-01", to: "2026-02-28", tariffs: "all" });
  });

  it("pamięć porównań należy do providera i czyści się po zmianie plików", async () => {
    loginAs();
    mockApi();
    const context = renderProvider();
    await waitFor(() => expect(context.selectedFileId).toBe("f1"));
    context.comparisonCache.set("klucz", { tariffs: [] });

    await act(() => context.refreshFiles());

    expect(context.comparisonCache.get("klucz")).toBeUndefined();
    const other = renderProvider();
    await waitFor(() => expect(other.selectedFileId).toBe("f1"));
    expect(other.comparisonCache).not.toBe(context.comparisonCache);
  });

  it("po wgraniu pliku pobiera dane od nowa i zmienia zakres ważności porównań", async () => {
    loginAs();
    const get = mockApi();
    const context = renderProvider();
    await waitFor(() => expect(context.selectedFileId).toBe("f1"));
    const scope = context.cacheScope;

    await act(() => context.refreshFiles());
    await act(() => context.selectFile("f1"));

    expect(dataCalls(get)).toHaveLength(2);
    expect(context.cacheScope).not.toBe(scope);
  });

  it("po zmianie profilu pobiera dane od nowa zamiast z pamięci", async () => {
    loginAs();
    const get = mockApi();
    const context = renderProvider();
    await waitFor(() => expect(context.selectedFileId).toBe("f1"));
    const scope = context.cacheScope;

    context.setUserVersion(2);
    await waitFor(() => expect(dataCalls(get)).toHaveLength(2));
    await act(() => context.selectFile("f1"));

    expect(dataCalls(get)).toHaveLength(2);
    expect(context.cacheScope).not.toBe(scope);
  });
});
