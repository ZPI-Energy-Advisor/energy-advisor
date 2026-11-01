import { act, render, screen } from "@testing-library/react";
import { BrowserRouter, Route, Routes, useLocation } from "react-router-dom";
import { describe, expect, it } from "vitest";
import SessionExpiredListener from "./SessionExpiredListener";
import { SESSION_EXPIRED_EVENT } from "../api/client";
import { loginAs } from "../test/auth";

function LoginProbe() {
  const { state } = useLocation();
  return (
    <p>
      logowanie, wygasła: {String(Boolean(state?.sessionExpired))}, from:{" "}
      {state?.from?.pathname ?? "brak"}
    </p>
  );
}

const renderAt = (path) => {
  window.history.replaceState(null, "", path);
  return render(
    <BrowserRouter>
      <SessionExpiredListener />
      <Routes>
        <Route path="/" element={<LoginProbe />} />
        <Route path="/prices" element={<p>ceny</p>} />
      </Routes>
    </BrowserRouter>,
  );
};

const expireSession = () =>
  act(() => {
    window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT));
  });

describe("SessionExpiredListener", () => {
  it("po wygaśnięciu sesji przenosi na logowanie z informacją, skąd użytkownik przyszedł", () => {
    renderAt("/prices?zakres=dzien");

    expireSession();

    expect(screen.getByText("logowanie, wygasła: true, from: /prices")).toBeTruthy();
    expect(window.history.state.usr.from.search).toBe("?zakres=dzien");
  });

  it("kilka zgłoszeń naraz nie nadpisuje zapamiętanej ścieżki", () => {
    renderAt("/prices");

    expireSession();
    expireSession();

    expect(screen.getByText("logowanie, wygasła: true, from: /prices")).toBeTruthy();
  });

  it("po wylogowaniu w innej karcie przenosi na logowanie", () => {
    renderAt("/prices");

    act(() => {
      window.dispatchEvent(new StorageEvent("storage", { key: "access_token", newValue: null }));
    });

    expect(screen.getByText("logowanie, wygasła: true, from: /prices")).toBeTruthy();
  });

  it("zmiana tokenów w innej karcie przy aktywnej sesji nie wylogowuje", () => {
    loginAs();
    renderAt("/prices");

    act(() => {
      window.dispatchEvent(new StorageEvent("storage", { key: "access_token", newValue: "nowy" }));
    });

    expect(screen.getByText("ceny")).toBeTruthy();
  });
});
