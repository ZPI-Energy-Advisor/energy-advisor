import { describe, expect, it } from "vitest";
import { dropRejectionMessage } from "./energyFiles";

const rejection = (...codes) => ({ file: {}, errors: codes.map((code) => ({ code })) });

describe("dropRejectionMessage", () => {
  it("dwa poprawne pliki naraz to za dużo plików, a nie zły format", () => {
    const message = dropRejectionMessage([rejection("too-many-files"), rejection("too-many-files")], 10);

    expect(message).toBe("Można wgrać tylko jeden plik naraz. Wybierz jeden plik.");
  });

  it("za dużo plików ma pierwszeństwo przed innymi powodami", () => {
    const message = dropRejectionMessage([rejection("too-many-files", "file-invalid-type"), rejection("too-many-files")], 10);

    expect(message).toMatch(/tylko jeden plik/);
  });

  it("zbyt duży plik", () => {
    expect(dropRejectionMessage([rejection("file-too-large")], 10)).toBe(
      "Plik jest za duży. Maksymalny rozmiar pliku to 10 MB.",
    );
  });

  it("zły format pliku", () => {
    expect(dropRejectionMessage([rejection("file-invalid-type")], 10)).toMatch(/rozszerzeniem \.csv lub \.json/);
  });
});
