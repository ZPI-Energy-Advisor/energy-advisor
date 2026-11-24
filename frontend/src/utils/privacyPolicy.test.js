import { describe, expect, it } from "vitest";
import { parsePolicy } from "./privacyPolicy";

describe("parsePolicy", () => {
  it("dzieli treść na nagłówki, akapity i listy", () => {
    const markdown = [
      "# Polityka",
      "",
      "Pierwsza linia akapitu",
      "i jego ciąg dalszy.",
      "",
      "## Prawa",
      "",
      "- **dostęp** do danych,",
      "- usunięcie danych",
      "  razem z kontem.",
      "",
      "Koniec.",
    ].join("\n");

    expect(parsePolicy(markdown)).toEqual([
      { type: "h1", text: "Polityka" },
      { type: "p", text: "Pierwsza linia akapitu i jego ciąg dalszy." },
      { type: "h2", text: "Prawa" },
      { type: "ul", items: ["**dostęp** do danych,", "usunięcie danych razem z kontem."] },
      { type: "p", text: "Koniec." },
    ]);
  });

  it("lista zaraz po akapicie zaczyna nowy blok", () => {
    expect(parsePolicy("Masz prawo do:\n- dostępu\n- sprzeciwu")).toEqual([
      { type: "p", text: "Masz prawo do:" },
      { type: "ul", items: ["dostępu", "sprzeciwu"] },
    ]);
  });

  it("pusta treść nie daje bloków", () => {
    expect(parsePolicy("\n\n")).toEqual([]);
  });
});
