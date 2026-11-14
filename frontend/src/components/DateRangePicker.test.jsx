import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import DateRangePicker from "./DateRangePicker";

describe("DateRangePicker", () => {
  it("przeskakuje na miesiąc okresu wybranego z zewnątrz (np. losowy dzień)", () => {
    const props = { min: "2026-09-20", max: "2026-10-20", onChange: vi.fn() };
    const { rerender } = render(<DateRangePicker {...props} from="2026-09-25" to="2026-09-25" />);
    expect(screen.getByText("wrzesień 2026")).toBeTruthy();

    rerender(<DateRangePicker {...props} from="2026-10-12" to="2026-10-12" />);

    expect(screen.getByText("październik 2026")).toBeTruthy();
    expect(screen.getByLabelText("2026-10-12").getAttribute("aria-pressed")).toBe("true");
  });
});
