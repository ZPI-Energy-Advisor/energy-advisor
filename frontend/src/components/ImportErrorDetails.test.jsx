import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import ImportErrorDetails from "./ImportErrorDetails";

const actionError = (index) => ({
  location: `act_${String(index).padStart(4, "0")}`,
  message: "suma profilu 1.95 kWh różni się od energy_kwh 1.50",
  device_id: "dev_wm_01",
  device_name: "Pralka Bosch",
  action_id: `act_${String(index).padStart(4, "0")}`,
});

describe("ImportErrorDetails", () => {
  it("pokazuje zwykły tekst błędu", () => {
    render(<ImportErrorDetails error="Wymagany plik .csv lub .json" />);

    expect(screen.getByText("Wymagany plik .csv lub .json")).toBeTruthy();
  });

  it("wypisuje błędy pliku urządzeń z nazwą urządzenia", () => {
    const error = {
      message: "Plik urządzeń zawiera błędy (2).",
      errors: [
        actionError(16),
        { location: "dev_x_01", message: "brak pola device_category", device_id: "dev_x_01", device_name: null, action_id: null },
      ],
      errors_count: 2,
    };

    render(<ImportErrorDetails error={error} />);

    expect(screen.getByText("Plik urządzeń zawiera błędy (2).")).toBeTruthy();
    expect(screen.getByText("Pralka Bosch (act_0016):")).toBeTruthy();
    expect(screen.getByText("dev_x_01:")).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("pokazuje 10 pierwszych błędów i rozwija resztę", () => {
    const errors = Array.from({ length: 12 }, (_, index) => actionError(index + 1));

    render(<ImportErrorDetails error={{ message: "Plik urządzeń zawiera błędy (12).", errors, errors_count: 12 }} />);

    expect(screen.getAllByRole("listitem")).toHaveLength(10);
    fireEvent.click(screen.getByRole("button", { name: "Pokaż wszystkie (12)" }));
    expect(screen.getAllByRole("listitem")).toHaveLength(12);
  });

  it("informuje o błędach, których backend nie przesłał", () => {
    const errors = Array.from({ length: 3 }, (_, index) => actionError(index + 1));

    render(<ImportErrorDetails error={{ message: "Plik urządzeń zawiera błędy (799).", errors, errors_count: 799 }} />);

    expect(screen.getByText(/…i 796 błędów więcej/)).toBeTruthy();
  });
});
