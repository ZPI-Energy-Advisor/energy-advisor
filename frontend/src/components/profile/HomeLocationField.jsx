import { useState } from "react";
import { FiMapPin } from "react-icons/fi";
import { POLAND_BOUNDS, addressKey } from "../../utils/profileForm";
import { formatNumber } from "../../utils/format";

const formatCoordinate = (value, positive, negative) =>
  `${formatNumber(Math.abs(value), 4)}° ${value >= 0 ? positive : negative}`;

const insidePoland = (latitude, longitude) =>
  latitude >= POLAND_BOUNDS.minLatitude &&
  latitude <= POLAND_BOUNDS.maxLatitude &&
  longitude >= POLAND_BOUNDS.minLongitude &&
  longitude <= POLAND_BOUNDS.maxLongitude;

const GEOLOCATION_ERRORS = {
  1: "Przeglądarka nie dała zgody na odczyt położenia.",
  2: "Nie udało się ustalić położenia.",
  3: "Ustalanie położenia trwało zbyt długo.",
};

function describe(location, base) {
  const name = location.label ?? base.town;
  switch (location.source) {
    case "postal_code":
      return base.postal_code ? `${name}, ${base.postal_code}` : name;
    case "town":
      return base.postal_code
        ? `${name} (kodu ${base.postal_code} nie ma w OpenStreetMap, więc przyjęliśmy miejscowość z jego regionu)`
        : name;
    case "manual":
      return "Położenie wskazane przez Ciebie";
    default:
      return `Okolice: ${location.label}`;
  }
}

const LOOKUP_TONES = { ambiguous: "text-amber-700", unavailable: "text-amber-700", invalid: "text-red-600" };

function HomeLocationField({ id, base, lookup, onChange, error }) {
  const [status, setStatus] = useState(null);
  const location = base.location;
  const current = Boolean(location) && location.address === addressKey(base);
  const canLocate = typeof navigator !== "undefined" && Boolean(navigator.geolocation);

  const locateWithBrowser = () => {
    setStatus({ tone: "info", text: "Ustalanie położenia..." });
    navigator.geolocation.getCurrentPosition(
      ({ coords }) => {
        const latitude = Math.round(coords.latitude * 10000) / 10000;
        const longitude = Math.round(coords.longitude * 10000) / 10000;
        if (!insidePoland(latitude, longitude)) {
          setStatus({ tone: "error", text: "To położenie jest poza Polską, więc zostaje lokalizacja z kodu pocztowego." });
          return;
        }
        onChange({ latitude, longitude, source: "manual", label: null, address: addressKey(base) });
        setStatus({ tone: "info", text: "Zapisz profil, żeby zachować to położenie." });
      },
      (geolocationError) => setStatus({ tone: "error", text: GEOLOCATION_ERRORS[geolocationError.code] ?? GEOLOCATION_ERRORS[2] }),
      { enableHighAccuracy: false, timeout: 10000, maximumAge: 600000 },
    );
  };

  const resetToPostalCode = () => {
    onChange(null);
    setStatus({ tone: "info", text: "Po zapisaniu wyznaczymy lokalizację z kodu pocztowego i miejscowości." });
  };

  return (
    <div className="text-sm sm:col-span-2">
      <span id={`${id}-label`} className="mb-2 block font-medium text-gray-700">Lokalizacja do prognozy pogody</span>
      <div id={id} aria-labelledby={`${id}-label`} className={`rounded-md border p-3 ${error ? "border-red-400" : "border-gray-200"}`}>
        {lookup?.status === "loading" && <p role="status" className="text-gray-600">Sprawdzanie adresu...</p>}
        {lookup?.status !== "loading" && !location && (
          <p className="text-gray-600">Wpisz kod pocztowy albo miejscowość i naciśnij Enter: pokażemy, gdzie jest dom.</p>
        )}
        {lookup?.status !== "loading" && location && !current && (
          <p className="text-gray-600">Adres się zmienił. Naciśnij Enter w polu albo przejdź dalej, żeby go sprawdzić.</p>
        )}
        {lookup?.status !== "loading" && location && current && (
          <>
            <p className="flex items-start gap-2 font-medium text-gray-900">
              <FiMapPin aria-hidden="true" className="mt-0.5 shrink-0 text-emerald-600" />
              <span>
                {describe(location, base)}
                <span className="block text-xs font-normal text-gray-500">
                  {formatCoordinate(location.latitude, "N", "S")}, {formatCoordinate(location.longitude, "E", "W")} ·{" "}
                  <a
                    className="text-emerald-700 underline"
                    href={`https://www.openstreetmap.org/?mlat=${location.latitude}&mlon=${location.longitude}#map=12/${location.latitude}/${location.longitude}`}
                    target="_blank"
                    rel="noreferrer noopener"
                  >
                    Pokaż na mapie
                  </a>
                </span>
              </span>
            </p>
            {location.approximate && (
              <p className="mt-2 text-xs text-amber-700">
                Nie udało się potwierdzić adresu: miejscowość nie pasuje do kodu pocztowego albo geokoder nie odpowiadał.
                Pogoda będzie przybliżona dla całego regionu. Sprawdź adres i zapisz profil jeszcze raz.
              </p>
            )}
          </>
        )}
        {lookup?.message && lookup.status !== "loading" && (
          <p role="status" className={`mt-2 text-xs ${LOOKUP_TONES[lookup.status] ?? "text-gray-600"}`}>{lookup.message}</p>
        )}
        <div className="mt-3 flex flex-wrap gap-3">
          {canLocate && (
            <button type="button" onClick={locateWithBrowser} className="font-medium text-emerald-700 hover:underline">
              Użyj mojej lokalizacji
            </button>
          )}
          {location?.source === "manual" && (
            <button type="button" onClick={resetToPostalCode} className="font-medium text-gray-700 hover:underline">
              Wyznacz z kodu pocztowego
            </button>
          )}
        </div>
        {status && (
          <p role="status" className={`mt-2 text-xs ${status.tone === "error" ? "text-red-600" : "text-gray-600"}`}>{status.text}</p>
        )}
      </div>
      {error && <p className="mt-1.5 text-xs text-red-600">{error}</p>}
      <p className="mt-1.5 text-xs text-gray-500">
        Wystarczy dokładność do kilku kilometrów. Do wyznaczenia współrzędnych wysyłamy do OpenStreetMap tylko kod pocztowy i
        miejscowość. Dane adresowe ©{" "}
        <a className="underline" href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer noopener">
          współtwórcy OpenStreetMap
        </a>
        .
      </p>
    </div>
  );
}

export default HomeLocationField;
