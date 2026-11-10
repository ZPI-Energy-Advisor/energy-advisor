import { useCallback, useEffect, useState } from "react";
import apiClient from "../api/client";
import { useCurrentUser } from "../hooks/useCurrentUser";
import { useEnergyFiles } from "../hooks/useEnergyFiles";
import { getApiErrorMessage } from "../utils/energyFiles";

const BUTTON = "px-4 py-2 rounded text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed";
const PRIMARY = `${BUTTON} bg-emerald-600 text-white hover:bg-emerald-700`;
const SECONDARY = `${BUTTON} border border-gray-300 text-gray-700 hover:bg-gray-50`;

const devicesLabel = (count) => {
  if (count === 1) return "1 urządzenie";
  const lastDigit = count % 10;
  const lastTwo = count % 100;
  const few = lastDigit >= 2 && lastDigit <= 4 && (lastTwo < 12 || lastTwo > 14);
  return `${count} ${few ? "urządzenia" : "urządzeń"}`;
};

// Kręcące się kółko na przycisku w trakcie akcji: podłączenie czeka, aż hub uruchomi urządzenia (kilka sekund).
function Spinner() {
  return <span aria-hidden="true" className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />;
}

function ActionButton({ className, onClick, disabled, busy, busyLabel, children }) {
  return (
    <button type="button" className={`${className} inline-flex items-center justify-center gap-2`} onClick={onClick} disabled={disabled} aria-busy={busy}>
      {busy && <Spinner />}
      {busy ? busyLabel : children}
    </button>
  );
}

// Dom symulowany przez hub Smart Home. Widzi go tylko właściciel (HUB_HOME_USER_EMAIL).
// Stan jest pobierany ponownie po każdej zmianie listy plików, bo import i usunięcie pliku
// właściciela wysyłają rejestr urządzeń do huba.
function HomeConnectionPanel() {
  const { me } = useCurrentUser();
  const { files } = useEnergyFiles();
  const isOwner = Boolean(me?.home_owner);
  const [home, setHome] = useState(null);
  const [error, setError] = useState(null);
  // Akcja w toku: "connect", "resend" albo "disconnect"; blokuje wszystkie przyciski.
  const [busyAction, setBusyAction] = useState(null);
  const [reloadKey, setReloadKey] = useState(0);
  const reload = useCallback(() => setReloadKey((key) => key + 1), []);

  useEffect(() => {
    if (!isOwner) return undefined;
    // Odpowiedź sprzed kolejnej zmiany plików nie może nadpisać nowszego stanu.
    let cancelled = false;
    apiClient.get("/home").then(
      ({ data }) => {
        if (cancelled) return;
        setHome(data);
        setError(null);
      },
      (err) => {
        if (!cancelled) setError(getApiErrorMessage(err, "Nie udało się pobrać stanu domu."));
      },
    );
    return () => {
      cancelled = true;
    };
  }, [isOwner, files, reloadKey]);

  const run = async (action, request, fallback) => {
    setBusyAction(action);
    try {
      const { data } = await request();
      setHome(data);
      setError(null);
    } catch (err) {
      setError(getApiErrorMessage(err, fallback));
    } finally {
      setBusyAction(null);
    }
  };

  const connect = (action = "connect") => run(action, () => apiClient.post("/home/connect"), "Nie udało się podłączyć domu.");
  const disconnect = () => run("disconnect", () => apiClient.delete("/home"), "Nie udało się odłączyć domu.");
  const isBusy = busyAction !== null;

  if (!isOwner) return null;

  const pending = home?.sync.status === "pending";

  return (
    <section className="mb-6 md:mb-8 bg-white border border-gray-200 rounded-lg p-4 md:p-6 shadow-sm" aria-label="Dom Smart Home">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h3 className="font-bold text-gray-900">Dom Smart Home</h3>
          {home && (
            <p className="text-sm text-gray-600 mt-1">
              {home.connected
                ? `Podłączony · ${devicesLabel(home.devices_count)} z plików urządzeń w symulacji`
                : "Podłącz dom, aby hub uruchomił urządzenia z Twoich plików urządzeń."}
            </p>
          )}
        </div>
        {home && (
          <div className="flex flex-wrap gap-2">
            {home.connected ? (
              <>
                {pending && (
                  <ActionButton className={PRIMARY} onClick={() => connect("resend")} disabled={isBusy} busy={busyAction === "resend"} busyLabel="Wysyłanie...">
                    Wyślij urządzenia ponownie
                  </ActionButton>
                )}
                <ActionButton className={SECONDARY} onClick={disconnect} disabled={isBusy} busy={busyAction === "disconnect"} busyLabel="Odłączanie...">
                  Odłącz dom
                </ActionButton>
              </>
            ) : (
              <ActionButton className={PRIMARY} onClick={() => connect()} disabled={isBusy} busy={busyAction === "connect"} busyLabel="Podłączanie...">
                Podłącz dom
              </ActionButton>
            )}
          </div>
        )}
      </div>

      {pending && home.sync.error && (
        <p className="mt-4 p-3 rounded border border-amber-200 bg-amber-50 text-sm text-amber-800" role="status">
          {home.sync.error}
        </p>
      )}
      {error && (
        <p className="mt-4 p-3 rounded border border-red-200 bg-red-50 text-sm text-red-700" role="alert">
          {error}{" "}
          {!home && (
            <button type="button" onClick={reload} className="font-semibold underline">
              Spróbuj ponownie
            </button>
          )}
        </p>
      )}
    </section>
  );
}

export default HomeConnectionPanel;
