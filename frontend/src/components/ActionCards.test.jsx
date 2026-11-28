import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import ActionCards from "./ActionCards";

const ITEMS = [
  {
    key: "a1",
    name: "Bojler",
    program: "woda na 06:00",
    before: "28.11 00:15–00:30, 06:15–06:30, 07:00–07:15, 07:45–08:00, 10:30–10:45",
    after: "28.11 05:00–05:45",
    afterNote: null,
    costBefore: 6.38,
    costAfter: 4.98,
  },
];

describe("ActionCards", () => {
  it("pokazuje urządzenie, godziny i koszt przed i po", () => {
    render(<ActionCards items={ITEMS} labels={{ before: "Bez planu", after: "Według planu" }} ariaLabel="Urządzenia" />);

    expect(screen.getByText("Bojler")).toBeTruthy();
    expect(screen.getByText("28.11 05:00–05:45")).toBeTruthy();
    expect(screen.getByText("6,38 zł")).toBeTruthy();
    expect(screen.getByText("4,98 zł")).toBeTruthy();
  });

  it("długą listę okresów zwija do trzech z „i N więcej”", () => {
    const { container } = render(<ActionCards items={ITEMS} labels={{ before: "Przed", after: "Po" }} ariaLabel="Urządzenia" />);

    expect(screen.getByText("i 2 więcej")).toBeTruthy();
    const details = container.querySelector("details");
    expect(details.open).toBe(false);
    fireEvent.click(screen.getByText("i 2 więcej"));
    expect(details.textContent).toContain("10:30–10:45");
  });
});
