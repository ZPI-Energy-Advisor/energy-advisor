import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { FiChevronLeft, FiChevronRight, FiCloud, FiSun, FiThermometer } from "react-icons/fi";
import apiClient from "../api/client";
import { ChartSkeleton, PageSkeleton } from "../components/Skeleton";
import PvAccuracyChart from "../components/pv/PvAccuracyChart";
import PvDayChart from "../components/pv/PvDayChart";
import MoreInfo from "../components/MoreInfo";
import { formatDate, getApiErrorMessage } from "../utils/energyFiles";
import { formatKw, formatKwp, formatNumber } from "../utils/format";
import {
  addDays,
  dayName,
  describeAccuracy,
  describePanels,
  describePeriods,
  describeConsumption,
  describeSettlement,
  describeWeatherSource,
  formatDayLong,
  formatKwh,
  formatPercent,
  formatPln,
  formatTemperatureRange,
  selfShare,
} from "../utils/pv";
import { CARD, ICON_BUTTON, alertClass, buttonClass } from "../components/uiStyles";

const EARLIEST_DAY = "2000-01-01";
const DAY_LOAD_DELAY_MS = 250;

function DayCard({ summary, today, selected, onSelect }) {
  const name = dayName(summary.date, today);
  const temperature = formatTemperatureRange(summary.temperature_min_c, summary.temperature_max_c);
  return (
    <button
      type="button"
      onClick={() => onSelect(summary.date)}
      aria-pressed={selected}
      className={`rounded-lg border bg-white p-4 text-left shadow-sm transition-shadow hover:shadow-md md:p-5 ${
        selected ? "border-amber-400 ring-2 ring-amber-200" : "border-gray-100"
      }`}
    >
      <p className="text-sm font-medium text-gray-500">
        {name} · {formatDayLong(summary.date)}
      </p>
      {summary.available ? (
        <>
          <p className="mt-2 flex items-baseline gap-2">
            <FiSun aria-hidden="true" className="self-center text-amber-500" />
            <span className="text-2xl font-bold text-gray-900">{formatNumber(summary.total_kwh, 1)}</span>
            <span className="text-sm font-semibold text-amber-700">kWh</span>
          </p>
          <p className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-gray-500">
            {summary.cloud_cover_pct != null && (
              <span className="flex items-center gap-1" title="Średnie zachmurzenie nieba w godzinach ze słońcem">
                <FiCloud aria-hidden="true" /> zachmurzenie w dzień {summary.cloud_cover_pct}%
              </span>
            )}
            {temperature && (
              <span className="flex items-center gap-1" title="Najniższa i najwyższa temperatura w ciągu doby">
                <FiThermometer aria-hidden="true" /> {temperature}
              </span>
            )}
          </p>
          {summary.basis !== "weather" && (
            <p className="mt-2 text-xs text-amber-700">Część pogody to średnia z ostatnich dni.</p>
          )}
        </>
      ) : (
        <p className="mt-3 text-sm text-gray-500">Brak prognozy pogody.</p>
      )}
    </button>
  );
}

function Tile({ label, value, hint }) {
  return (
    <div className="rounded-lg border border-gray-100 bg-gray-50 p-3 md:p-4">
      <p className="text-xs font-medium text-gray-500">{label}</p>
      <p className="mt-1 text-lg font-bold text-gray-900 md:text-xl">{value}</p>
      {hint && <p className="mt-0.5 text-xs text-gray-500">{hint}</p>}
    </div>
  );
}

function missingConsumptionText(detail, overview) {
  if (!overview.first_data_day) {
    return (
      <>
        <Link to="/upload" className="text-emerald-700 underline">Wgraj plik z licznika albo urządzeń</Link>, żeby zobaczyć, ile prądu z paneli dom zużyje sam, a ile odda do sieci.
      </>
    );
  }
  if (detail.kind === "past") {
    return `W Twoich plikach nie ma odczytów z tego dnia, więc nie pokazujemy zużycia domu ani bilansu. Pliki obejmują: ${describePeriods(overview.data_periods)}.`;
  }
  return `Zużycie szacujemy z odczytów z ostatnich 60 dni przed tym dniem, a najnowsze dane w Twoich plikach są z ${formatDate(overview.last_data_day)}. Wgraj nowszy plik, żeby zobaczyć bilans.`;
}

function Balance({ detail, overview }) {
  const { installation } = overview;
  const { balance } = detail;
  const estimated = detail.consumption_source === "typical";
  const productionLabel = detail.actual_kwh != null ? "Produkcja z pliku" : detail.kind === "past" ? "Produkcja z modelu" : "Produkcja z prognozy";
  if (!balance) {
    return (
      <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Tile label={productionLabel} value={formatKwh(detail.actual_kwh ?? detail.model_kwh)} />
        <p className="self-center text-sm text-gray-600">{missingConsumptionText(detail, overview)}</p>
      </div>
    );
  }
  const value = balance.value;
  const settlement = installation.settlement === "net_billing" ? "do depozytu" : "w opuście";
  return (
    <>
      {estimated && (
        <p className="mt-4 text-sm text-gray-600">
          Zużycie domu to szacunek ze średniej z Twoich plików (linia przerywana).
        </p>
      )}
      <div className="mt-4 grid grid-cols-2 gap-3 lg:grid-cols-5">
        <Tile
          label={productionLabel}
          value={formatKwh(balance.production_kwh)}
          hint={detail.actual_kwh != null && detail.model_kwh != null ? `model: ${formatKwh(detail.model_kwh)}` : null}
        />
        <Tile label={estimated ? "Zużycie domu (szacunek)" : "Zużycie domu"} value={formatKwh(balance.consumption_kwh)} hint={describeConsumption(detail)} />
        <Tile label="Zużyte od razu" value={formatKwh(balance.self_kwh)} hint={`${formatPercent(selfShare(balance))} produkcji`} />
        <Tile label="Oddane do sieci" value={formatKwh(balance.export_kwh)} hint={`z sieci: ${formatKwh(balance.import_kwh)}`} />
        <Tile
          label="Wartość prądu z paneli"
          value={value ? formatPln(value.self_pln + value.export_pln) : "—"}
          hint={!value ? "bez stawek taryfy" : value.export_price == null && balance.export_kwh > 0
            ? `${formatPln(value.self_pln)} mniej za prąd; oddanie bez wyceny`
            : `${formatPln(value.self_pln)} mniej za prąd + ${formatPln(value.export_pln)} ${settlement}`}
        />
      </div>
      <MoreInfo className="mt-3">
      <p>
        Liczymy w godzinach, jak operator: w każdej godzinie prąd z paneli najpierw pokrywa zużycie domu w tej godzinie,
        a nadwyżka idzie do sieci. Każdą godzinę wyceniamy jej własną ceną, a poniżej są średnie z tego dnia.{" "}
        {value?.purchase_price != null && (
          <>
            1 kWh zużyta od razu oszczędza średnio ok. <strong>{formatPln(value.purchase_price)}</strong> w godzinach,
            w których zużywasz prąd z paneli (cena z sieci z dystrybucją i VAT).{" "}
          </>
        )}
        {value?.export_price != null && (
          <>
            1 kWh oddana do sieci daje średnio ok. <strong>{formatPln(value.export_price)}</strong> {settlement} w godzinach,
            w których oddajesz
            {value.export_price_estimated && " (szacunek z ostatnich dni)"}.{" "}
          </>
        )}
        {value && installation.settlement === "net_billing" &&
          "Depozyt pokrywa tylko część rachunku za energię, bez opłat dystrybucyjnych."}
      </p>
      </MoreInfo>
    </>
  );
}

function AccuracyBody({ accuracy, onSelect }) {
  if (accuracy?.days?.length) {
    return (
      <>
        <PvAccuracyChart days={accuracy.days} onSelect={onSelect} />
        {accuracy.days_without_weather > 0 && (
          <p className="mt-2 text-xs text-gray-500">
            Dla {accuracy.days_without_weather} dni z produkcją pogoda z archiwum jeszcze się pobiera; pojawią się po odświeżeniu.
          </p>
        )}
      </>
    );
  }
  if (accuracy?.days_without_weather > 0) {
    return (
      <p className="text-sm text-gray-500">
        Pobieramy pogodę z archiwum dla {accuracy.days_without_weather} dni z produkcją z Twoich plików. Odśwież stronę za kilka minut.
      </p>
    );
  }
  return (
    <p className="text-sm text-gray-500">
      Nie ma jeszcze dni z produkcją z falownika. <Link to="/upload" className="text-emerald-700 underline">Wgraj plik urządzeń z instalacją PV</Link>, żeby dopasować prognozę do Twojego domu.
    </p>
  );
}

function PvPage() {
  const [overview, setOverview] = useState(null);
  const [overviewError, setOverviewError] = useState(null);
  const [selected, setSelected] = useState(null);
  const [detail, setDetail] = useState(null);
  const [detailError, setDetailError] = useState(null);
  const [isLoadingDay, setIsLoadingDay] = useState(false);
  const [accuracy, setAccuracy] = useState(null);
  const dayRequest = useRef(0);
  const dayTimer = useRef(null);
  const daySection = useRef(null);

  const loadDay = useCallback((day) => {
    const request = ++dayRequest.current;
    apiClient.get("/pv/day", { params: { date: day } })
      .then(({ data }) => {
        if (request !== dayRequest.current) return;
        setDetail(data);
        setDetailError(null);
      })
      .catch((error) => {
        if (request !== dayRequest.current) return;
        setDetail(null);
        setDetailError(getApiErrorMessage(error, "Nie udało się wczytać tego dnia."));
      })
      .finally(() => {
        if (request === dayRequest.current) setIsLoadingDay(false);
      });
  }, []);

  const selectDay = useCallback((day, { immediate = false } = {}) => {
    setSelected(day);
    setIsLoadingDay(true);
    clearTimeout(dayTimer.current);
    if (immediate) loadDay(day);
    else dayTimer.current = setTimeout(() => loadDay(day), DAY_LOAD_DELAY_MS);
  }, [loadDay]);

  useEffect(() => () => clearTimeout(dayTimer.current), []);

  const loadOverview = useCallback(() => {
    let cancelled = false;
    apiClient.get("/pv/overview")
      .then(({ data }) => {
        if (cancelled) return;
        setOverview(data);
        selectDay(data.today, { immediate: true });
      })
      .catch((error) => {
        if (!cancelled) setOverviewError({ status: error.response?.status, message: getApiErrorMessage(error, null) });
      });
    apiClient.get("/pv/accuracy")
      .then(({ data }) => {
        if (!cancelled) setAccuracy(data);
      })
      .catch(() => {
        if (!cancelled) setAccuracy(null);
      });
    return () => {
      cancelled = true;
    };
  }, [selectDay]);

  useEffect(() => loadOverview(), [loadOverview]);

  const retry = () => {
    setOverviewError(null);
    loadOverview();
  };

  if (overviewError) {
    const { status } = overviewError;
    const profileProblem = status === 404 || status === 409;
    const title = status === 404
      ? "Profil nie ma instalacji fotowoltaicznej."
      : status === 409
        ? overviewError.message ?? "Uzupełnij profil."
        : status === 429
          ? overviewError.message
          : "Nie udało się połączyć z serwerem.";
    const text = status === 404
      ? "Dodaj panele w profilu (moc, kierunek i nachylenie), a pokażemy prognozę produkcji na najbliższe dni, ile prądu z paneli zużyje dom i ile to jest warte."
      : status === 409
        ? "Do prognozy potrzebujemy lokalizacji domu i paneli z profilu."
        : status === 429
          ? "Odczekaj chwilę i spróbuj ponownie."
          : "Sprawdź połączenie i spróbuj ponownie za chwilę.";
    return (
      <div className="mx-auto max-w-3xl pb-12">
        <h2 className="mb-4 text-xl font-bold text-gray-900">Fotowoltaika</h2>
        <div className={CARD}>
          <FiSun aria-hidden="true" className="mb-3 text-3xl text-amber-500" />
          <p className="font-medium text-gray-900">{title}</p>
          <p className="mt-2 text-sm text-gray-600">{text}</p>
          {profileProblem ? (
            <Link to="/profile" className="mt-4 inline-block font-medium text-emerald-700 hover:underline">Przejdź do profilu</Link>
          ) : (
            <button type="button" onClick={retry} className={`${buttonClass("primary")} mt-4`}>
              Spróbuj ponownie
            </button>
          )}
        </div>
      </div>
    );
  }
  if (!overview) return <PageSkeleton label="Ładowanie fotowoltaiki..." />;

  const { installation, calibration, today } = overview;
  const minDay = EARLIEST_DAY;
  const isPast = detail?.kind === "past";
  const modelLabel = isPast ? "Produkcja z modelu (z pogody)" : "Prognoza produkcji";
  const estimatedConsumption = detail?.consumption_source === "typical";
  const consumptionLabel = estimatedConsumption ? "Szacowane zużycie domu" : "Zużycie domu";
  const weatherSource = detail ? describeWeatherSource(detail) : null;

  return (
    <div className="mx-auto max-w-6xl pb-12">
      <div className="mb-6 border-b border-gray-200 pb-4">
        <h2 className="text-xl font-bold text-gray-900">Fotowoltaika</h2>
        <p className="mt-1 text-sm text-gray-600">
          {describePanels(installation)}
          {installation.inverter_kw ? `, falownik ${formatKw(installation.inverter_kw)}` : ""} · {describeSettlement(installation)}
          {overview.location_label ? ` · ${overview.location_label}` : ""}
        </p>
        <p className="mt-1 text-sm text-gray-500">{describeAccuracy(calibration)}</p>
        {installation.estimated && (
          <p className="mt-2 text-sm text-amber-700">
            {calibration.effective_kwp
              ? `Panele są szacunkowe: moc (ok. ${formatKwp(calibration.effective_kwp)}) dopasowaliśmy do produkcji z Twoich plików, więc prognoza jest orientacyjna. `
              : "Panele są szacunkowe, więc prognoza jest orientacyjna. "}
            <Link to="/profile" className="underline">Uzupełnij panele w profilu</Link>.
          </p>
        )}
        {overview.approximate_location && (
          <p className="mt-2 text-sm text-amber-700">
            Lokalizacja domu jest przybliżona, więc pogoda dotyczy regionu. <Link to="/profile" className="underline">Popraw adres w profilu</Link>.
          </p>
        )}
      </div>

      <section aria-labelledby="pv-days" className="mb-8">
        <h3 id="pv-days" className="mb-3 font-bold text-gray-900">Najbliższe dni</h3>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          {overview.days.map((summary) => (
            <DayCard key={summary.date} summary={summary} today={today} selected={summary.date === selected} onSelect={selectDay} />
          ))}
        </div>
      </section>

      <section ref={daySection} aria-labelledby="pv-day" className={`${CARD} mb-8`}>
        <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <h3 id="pv-day" className="font-bold text-gray-900">
            {selected && (dayName(selected, today) ? `${dayName(selected, today)}, ` : "")}
            {selected && formatDayLong(selected)}
            {weatherSource && detail.date === selected && (
              <span className="ml-2 text-sm font-normal text-gray-500">{weatherSource}</span>
            )}
          </h3>
          <div className="flex items-center gap-2">
            <button type="button" aria-label="Poprzedni dzień" disabled={!selected || selected <= minDay} onClick={() => selectDay(addDays(selected, -1))} className={ICON_BUTTON}>
              <FiChevronLeft aria-hidden="true" />
            </button>
            <input
              type="date"
              aria-label="Dzień"
              value={selected ?? ""}
              min={minDay}
              max={overview.latest_day}
              onChange={(event) => event.target.value && selectDay(event.target.value)}
              className="rounded-md border border-gray-200 px-2 py-1.5 text-sm"
            />
            <button type="button" aria-label="Następny dzień" disabled={!selected || selected >= overview.latest_day} onClick={() => selectDay(addDays(selected, 1))} className={ICON_BUTTON}>
              <FiChevronRight aria-hidden="true" />
            </button>
            {selected !== today && (
              <button type="button" onClick={() => selectDay(today)} className="rounded-md px-2 py-1.5 text-sm font-medium text-emerald-700 hover:bg-emerald-50">Dziś</button>
            )}
          </div>
        </div>

        {overview.data_periods.length > 0 && (
          <p className="-mt-2 mb-3 text-xs text-gray-500">
            Dane z Twoich plików: {describePeriods(overview.data_periods)}.
          </p>
        )}

        {detailError ? (
          <p role="alert" className={alertClass("warning")}>{detailError}</p>
        ) : !detail ? (
          <ChartSkeleton label="Ładowanie dnia..." className="h-[300px]" />
        ) : (
          <div className={`transition-opacity ${isLoadingDay ? "opacity-60" : ""}`} aria-busy={isLoadingDay}>
            <PvDayChart
              intervals={detail.intervals}
              modelLabel={modelLabel}
              consumptionLabel={consumptionLabel}
              consumptionEstimated={estimatedConsumption}
            />
            <Balance detail={detail} overview={overview} />
            {detail.notes.length > 0 && (
              <ul className="mt-3 space-y-1 text-xs text-gray-500">
                {detail.notes.map((note) => <li key={note}>{note}</li>)}
              </ul>
            )}
          </div>
        )}
      </section>

      <section aria-labelledby="pv-accuracy" className={CARD}>
        <h3 id="pv-accuracy" className="mb-1 font-bold text-gray-900">Trafność prognozy</h3>
        <p className="mb-4 text-sm text-gray-600">
          Produkcja z Twoich plików urządzeń obok tego, co model policzył z pogody z tych dni.
        </p>
        <AccuracyBody
          accuracy={accuracy}
          onSelect={(day) => {
            selectDay(day, { immediate: true });
            daySection.current?.scrollIntoView?.({ behavior: "smooth", block: "start" });
          }}
        />
      </section>
    </div>
  );
}

export default PvPage;
