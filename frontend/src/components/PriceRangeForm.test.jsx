import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import PriceRangeForm from "./PriceRangeForm";

const BOUNDS = { from: "2026-01-01", to: "2026-11-25" };
const LAST_WEEK = { from: "2026-11-19", to: "2026-11-25" };

const renderForm = (props = {}) => {
  const onApply = vi.fn();
  render(<PriceRangeForm bounds={BOUNDS} appliedRange={LAST_WEEK} onApply={onApply} isLoading={false} {...props} />);
  return onApply;
};

describe("PriceRangeForm", () => {
  it("zakres z kalendarza stosuje dopiero przycisk „Pokaż ceny”", () => {
    const onApply = renderForm();
    // Wyświetlany okres: przycisk nieaktywny.
    expect(screen.getByRole("button", { name: "Pokaż ceny" }).disabled).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "2026-11-03" }));
    fireEvent.click(screen.getByRole("button", { name: "2026-11-10" }));

    expect(screen.getByText(/Wybrany okres/).textContent).toMatch(/03\.11\.2026 – 10\.11\.2026/);
    expect(onApply).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Pokaż ceny" }));
    expect(onApply).toHaveBeenCalledWith({ from: "2026-11-03", to: "2026-11-10" });
  });

  it("szybki wybór tylko zaznacza okres, a wykres zmienia dopiero „Pokaż ceny”", () => {
    const onApply = renderForm();
    expect(screen.getByRole("button", { name: "7 dni" }).getAttribute("aria-pressed")).toBe("true");

    fireEvent.click(screen.getByRole("button", { name: "Cały okres" }));

    expect(onApply).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Cały okres" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByText(/Wybrany okres/).textContent).toMatch(/01\.01\.2026 – 25\.11\.2026/);
    fireEvent.click(screen.getByRole("button", { name: "Pokaż ceny" }));
    expect(onApply).toHaveBeenCalledWith(expect.objectContaining({ from: "2026-01-01", to: "2026-11-25" }));
  });

  it("kalendarz pokazuje miesiąc końca okresu, także dla długiego zakresu", () => {
    renderForm({ appliedRange: { from: "2026-08-28", to: "2026-11-25" } });

    expect(screen.getByText("listopad 2026")).toBeTruthy();
    expect(screen.getByRole("button", { name: "2026-11-25" }).getAttribute("aria-pressed")).toBe("true");
  });

  it("dni spoza zapisanych cen są w kalendarzu niedostępne", () => {
    renderForm({ bounds: { from: "2026-11-10", to: "2026-11-25" }, appliedRange: { from: "2026-11-19", to: "2026-11-25" } });

    expect(screen.getByRole("button", { name: "2026-11-09" }).disabled).toBe(true);
    expect(screen.getByRole("button", { name: "2026-11-26" }).disabled).toBe(true);
    expect(screen.getByRole("button", { name: "2026-11-12" }).disabled).toBe(false);
  });
});
