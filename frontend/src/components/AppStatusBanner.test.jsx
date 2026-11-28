import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import AppStatusBanner from "./AppStatusBanner";

describe("AppStatusBanner", () => {
  it("bez zdarzeń nic nie pokazuje", () => {
    const { container } = render(<AppStatusBanner />);

    expect(container.textContent).toBe("");
  });

  it("po utracie internetu mówi o braku połączenia, a po powrocie znika", () => {
    render(<AppStatusBanner />);

    act(() => window.dispatchEvent(new Event("offline")));
    expect(screen.getByText(/Brak połączenia z internetem/)).toBeTruthy();

    act(() => window.dispatchEvent(new Event("online")));
    expect(screen.queryByText(/Brak połączenia z internetem/)).toBeNull();
  });

  it("nowa wersja aplikacji: przycisk Odśwież włącza ją", () => {
    const update = vi.fn();
    render(<AppStatusBanner />);

    act(() => window.dispatchEvent(new CustomEvent("pwa:update-ready", { detail: { update } })));
    fireEvent.click(screen.getByRole("button", { name: "Odśwież" }));

    expect(update).toHaveBeenCalled();
  });
});
