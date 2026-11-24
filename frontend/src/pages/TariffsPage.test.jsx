import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import apiClient from "../api/client";
import TariffsPage from "./TariffsPage";
import { EnergyFileContext } from "../context/energyFileContext";
import { CurrentUserContext } from "../context/currentUserContext";
import { createResponseCache } from "../utils/responseCache";
import { COMPARISON, PV_COMPARISON, chartRow, comparisonOf, entry } from "../test/tariffComparison";

const FILE = { id: "f1", file_name: "dom.csv", source_type: "meter", data_start: "2026-01-01", data_end: "2026-03-31" };
const RESULTS = {
  statistics: { days_analyzed: 31 },
  pricing: { operator: "TAURON", all_tariffs: true },
  chart_hourly: [chartRow("00:00", { G11: 1.1, G12: 0.6, "G11-dynamic": 0.9, "G12-dynamic": 0.5 })],
  chart_15min: [],
};

const fileContext = (overrides = {}) => ({
  isReady: true,
  results: RESULTS,
  isLoadingData: false,
  selectedFile: FILE,
  selectedFileId: FILE.id,
  viewSource: { fileId: FILE.id, range: null },
  cacheScope: "user-1|1|0",
  dateRange: { from: FILE.data_start, to: FILE.data_end },
  applyDateRange: vi.fn(),
  rangeError: null,
  clearRangeError: vi.fn(),
  dataError: null,
  clearDataError: vi.fn(),
  requireAllTariffs: vi.fn(),
  reloadData: vi.fn(),
  comparisonCache,
  files: [{ id: FILE.id, status: "completed" }],
  filesError: null,
  isLoadingFiles: false,
  reload: vi.fn(),
  ...overrides,
});

const USER = { isReady: true, loadError: null, profileTariff: { exists: true, needs_update: false }, refresh: vi.fn() };

const page = (context) => (
  <MemoryRouter>
    <CurrentUserContext.Provider value={USER}>
      <EnergyFileContext.Provider value={context}>
        <TariffsPage />
      </EnergyFileContext.Provider>
    </CurrentUserContext.Provider>
  </MemoryRouter>
);

const renderPage = (context = fileContext()) => render(page(context));

const deferred = () => {
  let resolve;
  const promise = new Promise((done) => {
    resolve = done;
  });
  return { promise, resolve: (data) => resolve({ data }) };
};

const respondWith = (...comparisons) => {
  const spy = vi.spyOn(apiClient, "get");
  comparisons.forEach((data) => spy.mockResolvedValueOnce({ data }));
  return spy;
};

const matrix = () => screen.getByRole("region", { name: "Porównanie taryf" });

let comparisonCache = createResponseCache();

beforeEach(() => {
  comparisonCache = createResponseCache();
});

describe("TariffsPage", () => {
  it("pokazuje macierz grup z różnicą do Twojej taryfy i najtańszą taryfą", async () => {
    const get = respondWith(COMPARISON);
    renderPage();

    const g12 = await screen.findByRole("group", { name: "Grupa G12" });
    expect(get).toHaveBeenCalledWith("/energy-files/f1/tariff-comparison", { params: {} });
    expect(document.querySelector("[aria-busy='true']")).toBeNull();
    const regular = within(g12).getByRole("button", { name: /^G12:/ });
    expect(regular.textContent).toMatch(/350,00 zł/);
    expect(regular.textContent).toMatch(/−50,00 zł względem Twojej taryfy/);
    expect(regular.textContent).toMatch(/za kWh 300,00 zł · opłaty mies\. 50,00 zł/);
    const dynamic = within(g12).getByRole("button", { name: /^G12 z ceną dynamiczną/ });
    expect(within(dynamic).getByText("★ Najtańsza")).toBeTruthy();
    expect(within(dynamic).getByText("Oferta dynamiczna")).toBeTruthy();

    const g11 = within(matrix()).getByRole("button", { name: /^G11:/ });
    expect(within(g11).getByText("Twoja")).toBeTruthy();
    expect(g11.textContent).not.toMatch(/względem/);
    const g13 = within(matrix()).getByRole("button", { name: /^G13:.*brak kwoty/ });
    expect(g13.textContent).toMatch(/Brak stawek abonamentowej/);
    expect(within(screen.getByRole("group", { name: "Grupa G13" })).getByText(/niedostępna/)).toBeTruthy();
  });

  it("pokazuje karty: Twoja taryfa, najtańsza i oszczędność w zł i % z oznaczonym szacunkiem miesięcznym", async () => {
    respondWith(COMPARISON);
    renderPage();

    const saving = await screen.findByRole("region", { name: "Możesz zaoszczędzić" });
    expect(saving.textContent).toMatch(/70,00 zł \(17,5%\)/);
    expect(saving.textContent).toMatch(/01\.01\.2026 – 31\.01\.2026 po przejściu na G12 z ceną dynamiczną · Oferta dynamiczna/);
    expect(saving.textContent).toMatch(/Szacunek: średnio ok\. 68,73 zł miesięcznie/);
    const own = screen.getByRole("region", { name: "Twoja taryfa" });
    expect(own.textContent).toMatch(/400,00 zł.*G11.*za kWh 350,00 zł · opłaty mies\. 50,00 zł/);
    const cheapest = screen.getByRole("region", { name: "Najtańsza" });
    expect(cheapest.textContent).toMatch(/330,00 zł.*G12 z ceną dynamiczną · Oferta dynamiczna.*za kWh 280,00 zł/);
  });

  it("bez szacunku miesięcznego, gdy backend go nie podał (krótki okres)", async () => {
    respondWith({ ...COMPARISON, recommendation: { ...COMPARISON.recommendation, monthly_saving_estimate: null } });
    renderPage();

    const saving = await screen.findByRole("region", { name: "Możesz zaoszczędzić" });
    expect(saving.textContent).not.toMatch(/Szacunek/);
  });

  it("potwierdza, gdy Twoja taryfa jest najtańsza", async () => {
    respondWith(comparisonOf([entry("G11", 300, { is_profile: true }), entry("G12", 350)]));
    renderPage();

    const card = await screen.findByRole("region", { name: "Rekomendacja" });
    expect(card.textContent).toMatch(/Zostań przy swojej taryfie.*Masz najtańszą taryfę w okresie 01\.01\.2026 – 31\.01\.2026/);
    expect(screen.queryByRole("region", { name: "Możesz zaoszczędzić" })).toBeNull();
  });

  it("przy różnicy poniżej złotówki rekomenduje obecną taryfę", async () => {
    respondWith(comparisonOf([entry("G11", 300.5, { is_profile: true }), entry("G12", 299.7)]));
    renderPage();

    const card = await screen.findByRole("region", { name: "Rekomendacja" });
    expect(card.textContent).toMatch(/Zostań przy swojej taryfie.*G12 wyszłaby taniej tylko o 0,80 zł/);
    expect(within(screen.getByRole("region", { name: "Najtańsza" })).getByText("G12")).toBeTruthy();
  });

  it("bez profilu wskazuje najtańszą taryfę bez kwoty oszczędności", async () => {
    respondWith(comparisonOf([entry("G11", 400), entry("G12", 330)], { from_profile: false }));
    renderPage();

    const card = await screen.findByRole("region", { name: "Najkorzystniejsza taryfa" });
    expect(card.textContent).toMatch(/G12.*Kwotę oszczędności pokażemy po uzupełnieniu profilu/);
    expect(screen.queryByText(/Możesz zaoszczędzić/)).toBeNull();
    expect(within(screen.getByRole("region", { name: "Twoja taryfa" })).getByRole("link", { name: "Uzupełnij profil" })).toBeTruthy();
  });

  it("gdy Twojej taryfy nie da się policzyć, nie podaje oszczędności i mówi dlaczego", async () => {
    respondWith(
      comparisonOf([
        entry("G11", 300),
        entry("G11-dynamic", null, { is_profile: true, note: "Brak cen RCE dla 2 dni." }),
      ], { selected_tariff: "G11-dynamic" }),
    );
    renderPage();

    expect((await screen.findByRole("region", { name: "Twoja taryfa" })).textContent).toMatch(/—.*Brak cen RCE dla 2 dni/);
    const card = screen.getByRole("region", { name: "Najkorzystniejsza taryfa" });
    expect(card.textContent).toMatch(/G11.*Twojej taryfy nie policzyliśmy w tym okresie/);
  });

  it("bez żadnej policzonej taryfy nie rekomenduje niczego", async () => {
    respondWith(comparisonOf([entry("G11", null, { is_profile: true, note: "Brak cen." })]));
    renderPage();

    const card = await screen.findByRole("region", { name: "Rekomendacja" });
    expect(card.textContent).toMatch(/—.*Bez kompletu cen nie wskażemy najkorzystniejszej taryfy/);
    expect(screen.getByRole("region", { name: "Najtańsza" }).textContent).toMatch(/Żadnej taryfy nie udało się policzyć/);
  });

  it("ostrzega, że taryf, których nie da się policzyć, nie rekomendujemy", async () => {
    respondWith(COMPARISON);
    renderPage();

    const warning = await screen.findByText(/Nie rekomendujemy taryf, których nie da się policzyć w tym okresie/);
    expect(warning.textContent).toMatch(/G13\. Powód jest przy każdej z nich w tabeli/);
    expect(within(warning).getByText("G13").getAttribute("title")).toBe("Brak stawek abonamentowej dla okresu 2 mies.");
  });

  it("przy PV porównuje kwoty do zapłaty po depozycie", async () => {
    respondWith(PV_COMPARISON);
    renderPage();

    const saving = await screen.findByRole("region", { name: "Możesz zaoszczędzić" });
    expect(saving.textContent).toMatch(/30,00 zł \(12%\).*po przejściu na G12/);
    expect(screen.getByRole("region", { name: "Twoja taryfa" }).textContent).toMatch(/250,00 zł/);
  });

  it("kliknięta taryfa trafia do szczegółów rachunku", async () => {
    respondWith(COMPARISON);
    renderPage();

    expect((await screen.findByRole("heading", { name: /Szczegóły rachunku/ })).textContent).toBe("Szczegóły rachunku: G11");
    fireEvent.click(within(matrix()).getByRole("button", { name: /^G12:/ }));

    const details = screen.getByRole("region", { name: "Szczegóły rachunku: G12" });
    expect(within(matrix()).getByRole("button", { name: /^G12:/ }).getAttribute("aria-pressed")).toBe("true");
    expect(within(details).getByText("Brak instalacji PV")).toBeTruthy();
    expect(within(details).queryByText("Depozyt")).toBeNull();
    expect(within(details).getByText(/przeskalowane z 31 dni danych/)).toBeTruthy();
    expect(within(details).getByText(/opłaty miesięczne za 31 z 59 dni/)).toBeTruthy();
    expect(within(details).getAllByRole("columnheader").map((cell) => cell.textContent)).toEqual([
      "Okres", "Energia", "Dystrybucja", "Opłaty", "VAT", "Brutto",
    ]);

    fireEvent.click(within(details).getByRole("button", { name: "Pokaż wszystkie składniki" }));
    const headers = within(details).getAllByRole("columnheader").map((cell) => cell.textContent);
    expect(headers).toContain("Opłata kogeneracyjna");
    expect(headers).not.toContain("Opłata handlowa");
    expect(headers).toHaveLength(13);
  });

  it("przy PV pokazuje brutto, depozyt i potrącenie oraz tryb PV", async () => {
    respondWith(PV_COMPARISON);
    renderPage();

    const details = await screen.findByRole("region", { name: "Szczegóły rachunku: G11" });
    expect(within(details).getByText("Net-billing")).toBeTruthy();
    expect(within(details).getByText("Depozyt").parentElement.textContent).toMatch(/80,00 zł/);
    expect(within(details).getByText("Potrącono z energii czynnej").parentElement.textContent).toMatch(/50,00 zł/);
    expect(within(details).getByText(/minus depozyt 50,00 zł/)).toBeTruthy();
    expect(within(matrix()).getByRole("button", { name: /^G12:/ }).textContent).toMatch(/brutto 260,00 zł, depozyt 70,00 zł/);
  });

  it("pokazuje uwagi silnika, taryfę zastępczą i taryfy nieobsługiwane", async () => {
    respondWith(
      comparisonOf([entry("G11", 100)], {
        from_profile: false,
        selection_note: "Operator TAURON nie ma w cenniku stawek taryfy G12w dla tego okresu, więc liczymy taryfę G11.",
        warnings: ["Plik zaczyna się 01.12.2025, a stawki taryfowe mamy od 01.01.2026."],
        unsupported_tariffs: [{ code: "G12r", name: "G12r", reason: "Strefy ogłasza operator." }],
      }),
    );
    renderPage();

    expect(await screen.findByText(/liczymy taryfę G11/)).toBeTruthy();
    expect(screen.getByText(/stawki taryfowe mamy od 01.01.2026/)).toBeTruthy();
    expect(screen.getByText("G12r").getAttribute("title")).toBe("Strefy ogłasza operator.");
    const own = screen.getByRole("region", { name: "Twoja taryfa" });
    expect(within(own).getByRole("link", { name: "Uzupełnij profil" }).getAttribute("href")).toBe("/profile");
  });

  it("wykres pokazuje domyślnie Twoją, najtańszą i zaznaczoną taryfę", async () => {
    respondWith(COMPARISON);
    renderPage();

    expect(await screen.findByRole("heading", { name: "Kiedy płacisz najwięcej" })).toBeTruthy();
    const showAll = screen.getByRole("checkbox", { name: "Pokaż wszystkie taryfy" });
    expect(showAll.checked).toBe(false);
  });

  it("czeka na ceny wszystkich taryf do wykresu", async () => {
    respondWith(COMPARISON);
    renderPage(fileContext({ results: { ...RESULTS, pricing: { operator: "TAURON", all_tariffs: false } } }));

    expect(await screen.findByText("Ładowanie wykresu...")).toBeTruthy();
  });

  it("pokazuje błąd porównania", async () => {
    vi.spyOn(apiClient, "get").mockRejectedValueOnce({ response: { data: { detail: "Brak cen RCE po 04.11.2026." } } });
    renderPage();

    expect((await screen.findByRole("alert")).textContent).toMatch(/Brak cen RCE/);
  });

  it("prosi o plik, gdy nic nie wybrano", () => {
    renderPage(fileContext({ selectedFile: null, selectedFileId: null, viewSource: null, results: null, files: [] }));

    expect(screen.getByText("Brak danych do porównania")).toBeTruthy();
  });

  it("zmiana zakresu zostawia poprzedni wynik, a powrót do niego nie wysyła zapytania", async () => {
    const pending = deferred();
    const get = vi.spyOn(apiClient, "get").mockResolvedValueOnce({ data: COMPARISON }).mockReturnValueOnce(pending.promise);
    const { rerender } = renderPage();
    await screen.findByRole("group", { name: "Grupa G12" });

    const january = { fileId: FILE.id, range: { from: "2026-01-01", to: "2026-01-31" } };
    rerender(page(fileContext({ viewSource: january })));
    expect(get).toHaveBeenLastCalledWith("/energy-files/f1/tariff-comparison", {
      params: { from: "2026-01-01", to: "2026-01-31" },
    });
    expect(screen.getByRole("group", { name: "Grupa G12" })).toBeTruthy();
    expect(document.querySelector("[aria-busy='true']")).toBeTruthy();

    await act(async () => pending.resolve(comparisonOf([entry("G11", 99, { is_profile: true })])));
    expect(screen.queryByRole("group", { name: "Grupa G12" })).toBeNull();

    rerender(page(fileContext()));
    expect(screen.getByRole("group", { name: "Grupa G12" })).toBeTruthy();
    expect(get).toHaveBeenCalledTimes(2);
  });

  it("ignoruje odpowiedź, która przyszła po nowszym zapytaniu", async () => {
    const slow = deferred();
    const fast = deferred();
    vi.spyOn(apiClient, "get").mockReturnValueOnce(slow.promise).mockReturnValueOnce(fast.promise);
    const { rerender } = renderPage(fileContext({ viewSource: { fileId: FILE.id, range: { from: "2026-01-01", to: "2026-01-31" } } }));
    rerender(page(fileContext({ viewSource: { fileId: FILE.id, range: { from: "2026-02-01", to: "2026-02-28" } } })));

    await act(async () => fast.resolve(comparisonOf([entry("G11", 222, { is_profile: true })])));
    await act(async () => slow.resolve(comparisonOf([entry("G11", 111, { is_profile: true })])));

    expect(within(matrix()).getByRole("button", { name: /^G11:/ }).textContent).toMatch(/222,00 zł/);
    expect(screen.queryByText(/111,00 zł/)).toBeNull();
  });

  it("nowa wersja konta albo plików pobiera porównanie od nowa", async () => {
    const get = respondWith(COMPARISON, COMPARISON);
    const { rerender } = renderPage();
    await screen.findByRole("group", { name: "Grupa G12" });

    rerender(page(fileContext({ cacheScope: "user-1|2|0" })));
    await screen.findByRole("group", { name: "Grupa G12" });

    expect(get).toHaveBeenCalledTimes(2);
  });

  it("prosi backend o ceny wszystkich taryf do wykresu tylko na tym ekranie", () => {
    respondWith(COMPARISON);
    const requireAllTariffs = vi.fn();
    const { unmount } = renderPage(fileContext({ requireAllTariffs }));
    unmount();

    expect(requireAllTariffs.mock.calls).toEqual([[true], [false]]);
  });

  it("przy pierwszym wejściu pyta o porównanie równolegle z danymi, nie czekając na nie", () => {
    const get = vi.spyOn(apiClient, "get").mockReturnValue(new Promise(() => {}));
    renderPage(fileContext({ isReady: false, selectedFile: null, selectedFileId: null, results: null, isLoadingData: true }));

    expect(get).toHaveBeenCalledWith("/energy-files/f1/tariff-comparison", { params: {} });
  });

  it("nie pyta o porównanie dla zakresu bez pomiarów", () => {
    const get = vi.spyOn(apiClient, "get");
    renderPage(fileContext({ results: { ...RESULTS, statistics: { days_analyzed: 0 } } }));

    expect(get).not.toHaveBeenCalled();
    expect(screen.getByText("Brak danych w wybranym zakresie")).toBeTruthy();
  });

  it("po błędzie porównania pozwala spróbować ponownie i nadal pokazuje wykres", async () => {
    vi.spyOn(apiClient, "get")
      .mockRejectedValueOnce({ response: { data: { detail: "Chwilowy błąd." } } })
      .mockResolvedValueOnce({ data: COMPARISON });
    renderPage();

    const alert = await screen.findByRole("alert");
    expect(screen.getByRole("heading", { name: "Kiedy płacisz najwięcej" })).toBeTruthy();
    expect(screen.queryByRole("checkbox", { name: "Pokaż wszystkie taryfy" })).toBeNull();
    fireEvent.click(within(alert).getByRole("button", { name: "Spróbuj ponownie" }));

    expect(await screen.findByRole("group", { name: "Grupa G12" })).toBeTruthy();
    expect(screen.queryByText("Chwilowy błąd.")).toBeNull();
  });

  it("gdy nie udało się pobrać cen do wykresu, pokazuje błąd zamiast wiecznego ładowania", async () => {
    respondWith(COMPARISON);
    const reloadData = vi.fn();
    renderPage(
      fileContext({
        results: { ...RESULTS, pricing: { operator: "TAURON", all_tariffs: false } },
        dataError: "Nie udało się pobrać danych wybranego pliku.",
        reloadData,
      }),
    );

    const chart = await screen.findByRole("region", { name: "Kiedy płacisz najwięcej" });
    expect(within(chart).queryByText("Ładowanie wykresu...")).toBeNull();
    fireEvent.click(within(chart).getByRole("button", { name: "Spróbuj ponownie" }));
    expect(reloadData).toHaveBeenCalledTimes(1);
  });

  it("szczegóły pokazują zużycie w okresie i energię czynną brutto", async () => {
    respondWith(comparisonOf([entry("G11", 400, { is_profile: true, active_energy_gross: 210.5 })]));
    renderPage();

    const details = await screen.findByRole("region", { name: "Szczegóły rachunku: G11" });
    expect(within(details).getByText("Zużycie w okresie").nextSibling.textContent).toBe("310 kWh");
    expect(within(details).getByText("Energia czynna brutto").nextSibling.textContent).toMatch(/210,50 zł/);
  });
});

