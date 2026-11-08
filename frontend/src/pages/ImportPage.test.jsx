import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import apiClient from "../api/client";
import ImportPage from "./ImportPage";

const navigate = vi.hoisted(() => vi.fn());
const refreshFiles = vi.hoisted(() => vi.fn());
const selectFile = vi.hoisted(() => vi.fn());

vi.mock("react-router-dom", async (importOriginal) => ({
  ...(await importOriginal()),
  useNavigate: () => navigate,
}));
vi.mock("../api/client", () => ({ default: { post: vi.fn() } }));
vi.mock("../components/EnergyFilesTable", () => ({ default: () => null }));
vi.mock("../hooks/useEnergyFiles", () => ({
  useEnergyFiles: () => ({ refreshFiles, selectFile }),
}));

const uploadResponse = {
  file_id: "file-1",
  file_name: "marzec.csv",
  message: "Symulacja zakończona",
  import_report: {
    format_label: "Tauron",
    rows_total: 96,
    rows_imported: 96,
    rows_ignored: 0,
    resolution_minutes: 15,
    skipped_rows: { count: 0, examples: [] },
  },
  summary: {
    statistics: {
      data_start: "2026-03-01",
      data_end: "2026-03-02",
      days_analyzed: 2,
      incomplete_days: ["2026-03-02"],
    },
  },
};

const uploadFile = async () => {
  const { container } = render(
    <MemoryRouter>
      <ImportPage />
    </MemoryRouter>,
  );
  const file = new File(["data"], "marzec.csv", { type: "text/csv" });
  fireEvent.change(container.querySelector("input[type=file]"), { target: { files: [file] } });
  fireEvent.click(await screen.findByText("Wyślij na serwer"));
  await screen.findByText("Sukces!");
};

describe("ImportPage po udanym imporcie", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiClient.post.mockResolvedValue({ data: uploadResponse });
  });

  it("pokazuje podsumowanie pliku i wybiera nowy plik", async () => {
    await uploadFile();

    expect(screen.getByText("marzec.csv")).toBeTruthy();
    expect(screen.getByText("01.03.2026 – 02.03.2026 · 2 dni")).toBeTruthy();
    expect(screen.getByText(/Dane zawierają 1 niepełny dzień/)).toBeTruthy();
    expect(selectFile).toHaveBeenCalledWith("file-1");
  });

  it("prowadzi do Dashboardu i porównania taryf", async () => {
    await uploadFile();

    fireEvent.click(screen.getByText("Przejdź do Dashboardu"));
    expect(navigate).toHaveBeenLastCalledWith("/dashboard");

    fireEvent.click(screen.getByText("Porównaj taryfy"));
    expect(navigate).toHaveBeenLastCalledWith("/results");
  });
});
