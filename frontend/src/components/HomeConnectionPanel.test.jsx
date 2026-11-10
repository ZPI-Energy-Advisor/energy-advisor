import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import apiClient from "../api/client";
import HomeConnectionPanel from "./HomeConnectionPanel";
import { CurrentUserContext } from "../context/currentUserContext";
import { EnergyFileContext } from "../context/energyFileContext";

const SYNCED = { status: "synced", synced_at: "2026-11-08T20:00:00Z", error: null };
const DISCONNECTED = { connected: false, connected_at: null, devices_count: 0, sync: SYNCED };
const CONNECTED = { connected: true, connected_at: "2026-11-08T20:00:00Z", devices_count: 3, sync: SYNCED };
const UNAVAILABLE = "Hub Smart Home jest niedostępny. Urządzenia zostaną wysłane przy kolejnej operacji.";

const renderPanel = ({ homeOwner = true, files = [] } = {}) =>
  render(
    <CurrentUserContext.Provider value={{ me: { home_owner: homeOwner } }}>
      <EnergyFileContext.Provider value={{ files }}>
        <HomeConnectionPanel />
      </EnergyFileContext.Provider>
    </CurrentUserContext.Provider>,
  );

describe("HomeConnectionPanel", () => {
  it("nie pokazuje się i nie pyta API, gdy dom należy do innego konta", () => {
    const get = vi.spyOn(apiClient, "get");

    const { container } = renderPanel({ homeOwner: false });

    expect(container.textContent).toBe("");
    expect(get).not.toHaveBeenCalled();
  });

  it("właściciel podłącza dom i widzi liczbę urządzeń", async () => {
    vi.spyOn(apiClient, "get").mockResolvedValue({ data: DISCONNECTED });
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({ data: CONNECTED });
    renderPanel();

    fireEvent.click(await screen.findByRole("button", { name: "Podłącz dom" }));

    expect(await screen.findByText(/Podłączony · 3 urządzenia/)).toBeTruthy();
    expect(post).toHaveBeenCalledWith("/home/connect");
    expect(screen.getByRole("button", { name: "Odłącz dom" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Wyślij urządzenia ponownie" })).toBeNull();
  });

  it("w trakcie podłączania pokazuje kręcące się kółko i blokuje przycisk", async () => {
    vi.spyOn(apiClient, "get").mockResolvedValue({ data: DISCONNECTED });
    let finish;
    vi.spyOn(apiClient, "post").mockReturnValue(new Promise((resolve) => { finish = resolve; }));
    renderPanel();

    fireEvent.click(await screen.findByRole("button", { name: "Podłącz dom" }));

    const busy = screen.getByRole("button", { name: "Podłączanie..." });
    expect(busy.disabled).toBe(true);
    expect(busy.getAttribute("aria-busy")).toBe("true");
    expect(busy.querySelector(".animate-spin")).toBeTruthy();

    finish({ data: CONNECTED });
    expect(await screen.findByRole("button", { name: "Odłącz dom" })).toBeTruthy();
    expect(document.querySelector(".animate-spin")).toBeNull();
  });

  it("przy zaległej wysyłce pokazuje powód i pozwala ją ponowić", async () => {
    const pending = { ...CONNECTED, sync: { status: "pending", synced_at: null, error: UNAVAILABLE } };
    vi.spyOn(apiClient, "get").mockResolvedValue({ data: pending });
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({ data: CONNECTED });
    renderPanel();

    expect((await screen.findByRole("status")).textContent).toBe(UNAVAILABLE);
    fireEvent.click(screen.getByRole("button", { name: "Wyślij urządzenia ponownie" }));

    await waitFor(() => expect(screen.queryByRole("status")).toBeNull());
    expect(post).toHaveBeenCalledWith("/home/connect");
  });

  it("odłącza dom", async () => {
    vi.spyOn(apiClient, "get").mockResolvedValue({ data: CONNECTED });
    const remove = vi.spyOn(apiClient, "delete").mockResolvedValue({ data: DISCONNECTED });
    renderPanel();

    fireEvent.click(await screen.findByRole("button", { name: "Odłącz dom" }));

    expect(await screen.findByRole("button", { name: "Podłącz dom" })).toBeTruthy();
    expect(remove).toHaveBeenCalledWith("/home");
  });

  it("pobiera stan ponownie po zmianie listy plików", async () => {
    const get = vi.spyOn(apiClient, "get").mockResolvedValue({ data: CONNECTED });
    const { rerender } = renderPanel();
    await screen.findByText(/Podłączony/);

    rerender(
      <CurrentUserContext.Provider value={{ me: { home_owner: true } }}>
        <EnergyFileContext.Provider value={{ files: [{ id: "nowy" }] }}>
          <HomeConnectionPanel />
        </EnergyFileContext.Provider>
      </CurrentUserContext.Provider>,
    );

    await waitFor(() => expect(get).toHaveBeenCalledTimes(2));
  });

  it("pokazuje błąd pobrania stanu z możliwością ponowienia", async () => {
    vi.spyOn(apiClient, "get")
      .mockRejectedValueOnce({ response: { data: { detail: "Symulacja Smart Home jest wyłączona." } } })
      .mockResolvedValueOnce({ data: DISCONNECTED });
    renderPanel();

    expect((await screen.findByRole("alert")).textContent).toContain("Symulacja Smart Home jest wyłączona.");
    fireEvent.click(screen.getByRole("button", { name: "Spróbuj ponownie" }));

    expect(await screen.findByRole("button", { name: "Podłącz dom" })).toBeTruthy();
  });
});
