import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import IncompleteDaysNotice from "./IncompleteDaysNotice";

describe("IncompleteDaysNotice", () => {
  it("podaje liczbę niepełnych dni i wypisuje ich daty", () => {
    render(<IncompleteDaysNotice statistics={{ incomplete_days: ["2026-03-01", "2026-03-09"] }} />);

    expect(screen.getByText(/Dane zawierają 2 niepełne dni/)).toBeTruthy();
    expect(screen.getByText("01.03.2026")).toBeTruthy();
    expect(screen.getByText("09.03.2026")).toBeTruthy();
  });

  it("nic nie renderuje, gdy dane są kompletne albo nie ma statystyk", () => {
    const { container, rerender } = render(<IncompleteDaysNotice statistics={{ incomplete_days: [] }} />);
    expect(container.innerHTML).toBe("");

    rerender(<IncompleteDaysNotice statistics={undefined} />);
    expect(container.innerHTML).toBe("");
  });
});
