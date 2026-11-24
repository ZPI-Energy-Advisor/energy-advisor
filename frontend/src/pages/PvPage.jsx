import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { FiChevronLeft, FiChevronRight, FiCloud, FiSun, FiThermometer } from "react-icons/fi";
import apiClient from "../api/client";
import { ChartSkeleton, PageSkeleton } from "../components/Skeleton";
import PvAccuracyChart from "../components/pv/PvAccuracyChart";
import PvDayChart from "../components/pv/PvDayChart";
import { formatDate, getApiErrorMessage } from "../utils/energyFiles";
import { formatNumber } from "../utils/format";
import {
  CONSUMPTION_SOURCES,
  addDays,
  dayName,
  describeAccuracy,
  describeArray,
  describeSettlement,
  formatDayLong,
  formatKwh,
  formatPercent,
  formatPln,
  formatTemperature,
  formatWindow,
  selfShare,
} from "../utils/pv";

const EARLIEST_DAY = "2000-01-01";

function DayCard({ summary, today, selected, onSelect }) {
  const name = dayName(summary.date, today);
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
          <p className="mt-1 text-xs text-gray-600">
            {summary.peak ? `Najwięcej ${formatWindow(summary.peak)}` : "Prawie bez produkcji"}
          </p>
          <p className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-gray-500">
            {summary.cloud_cover_pct != null && (
              <span className="flex items-center gap-1"><FiCloud aria-hidden="true" /> zachmurzenie {summary.cloud_cover_pct}%</span>
            )}
            {summary.temperature_min_c != null && (
              <span className="flex items-center gap-1">
                <FiThermometer aria-hidden="true" /> {formatTemperature(summary.temperature_min_c)} … {formatTemperature(summary.temperature_max_c)}
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

function Balance({ detail, installation }) {
  const { balance } = detail;
  const production = detail.actual_kwh ?? detail.model_kwh;
  if (!balance) {
    return (
      <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Tile label={detail.actual_kwh != null ? "Produkcja z pliku" : "Produkcja z prognozy"} value={formatKwh(production)} />
        <p className="self-center text-sm text-gray-500">
          Wgraj plik z licznika albo urządzeń, żeby zobaczyć, ile prądu z paneli dom zużyje sam, a ile odda do sieci.
        </p>
      </div>
    );
  }
  const value = balance.value;
  const settlement = installation.settlement === "net_billing" ? "do depozytu" : "w opuście";
  return (
    <>
      <div className="mt-4 grid grid-cols-2 gap-3 lg:grid-cols-5">
        <Tile
          label={detail.actual_kwh != null ? "Produkcja z pliku" : "Produkcja z prognozy"}
          value={formatKwh(balance.production_kwh)}
          hint={detail.actual_kwh != null && detail.model_kwh != null ? `model: ${formatKwh(detail.model_kwh)}` : null}
        />
        <Tile label="Zużycie domu" value={formatKwh(balance.consumption_kwh)} hint={CONSUMPTION_SOURCES[detail.consumption_source]} />
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
      {value && (value.purchase_price != null || value.export_price != null) && (
        <p className="mt-3 text-sm text-gray-600">
          {value.purchase_price != null && <>1 kWh z paneli zużyty od razu oszczędza ok. <strong>{formatPln(value.purchase_price)}</strong> (cena z sieci z dystrybucją). </>}
          {value.export_price != null && (
            <>
              Oddany do sieci daje ok. <strong>{formatPln(value.export_price)}</strong> {settlement}
              {value.export_price_estimated && " (szacunek z ostatnich dni)"}.{" "}
            </>
          )}
          {installation.settlement === "net_billing" &&
            "Depozyt pokrywa tylko część rachunku za energię, bez opłat dystrybucyjnych."}
        </p>
      )}
    </>
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
  const daySection = useRef(null);

  const loadDay = useCallback((day) => {
    const request = ++dayRequest.current;
    setIsLoadingDay(true);
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

  const selectDay = useCallback((day) => {
    setSelected(day);
    loadDay(day);
  }, [loadDay]);

  const loadOverview = useCallback(() => {
    let cancelled = false;
    apiClient.get("/pv/overview")
      .then(({ data }) => {
        if (cancelled) return;
        setOverview(data);
        selectDay(data.today);
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
        : "Nie udało się połączyć z serwerem.";
    const text = status === 404
      ? "Dodaj panele w profilu (moc, kierunek i nachylenie), a pokażemy prognozę produkcji na najbliższe dni, ile prądu z paneli zużyje dom i ile to jest warte."
      : status === 409
        ? "Do prognozy potrzebujemy lokalizacji domu i paneli z profilu."
        : "Sprawdź połączenie i spróbuj ponownie za chwilę.";
    return (
      <div className="mx-auto max-w-3xl pb-12">
        <h2 className="mb-4 text-xl font-bold text-gray-900">Fotowoltaika</h2>
        <div className="rounded-lg border border-gray-100 bg-white p-6 shadow-sm">
          <FiSun aria-hidden="true" className="mb-3 text-3xl text-amber-500" />
          <p className="font-medium text-gray-900">{title}</p>
          <p className="mt-2 text-sm text-gray-600">{text}</p>
          {profileProblem ? (
            <Link to="/profile" className="mt-4 inline-block font-medium text-emerald-700 hover:underline">Przejdź do profilu</Link>
          ) : (
            <button type="button" onClick={retry} className="mt-4 rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700">
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
  const modelLabel = isPast ? "Produkcja z modelu (pogoda z archiwum)" : "Prognoza produkcji";

  return (
    <div className="mx-auto max-w-6xl pb-12">
      <div className="mb-6 border-b border-gray-200 pb-4">
        <h2 className="text-xl font-bold text-gray-900">Fotowoltaika</h2>
        <p className="mt-1 text-sm text-gray-600">
          {formatNumber(installation.total_kwp, 2)} kWp ({installation.arrays.map(describeArray).join("; ")})
          {installation.inverter_kw ? `, falownik ${formatNumber(installation.inverter_kw, 1)} kW` : ""} · {describeSettlement(installation)}
          {overview.location_label ? ` · ${overview.location_label}` : ""}
        </p>
        <p className="mt-1 text-sm text-gray-500">{describeAccuracy(calibration)}</p>
        {installation.estimated && (
          <p className="mt-2 text-sm text-amber-700">
            Panele są szacunkowe, więc prognoza jest orientacyjna. <Link to="/profile" className="underline">Uzupełnij panele w profilu</Link>.
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

      <section ref={daySection} aria-labelledby="pv-day" className="mb-8 rounded-lg border border-gray-100 bg-white p-4 shadow-sm md:p-6">
        <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <h3 id="pv-day" className="font-bold text-gray-900">
            {selected && (dayName(selected, today) ? `${dayName(selected, today)}, ` : "")}
            {selected && formatDayLong(selected)}
            {detail && (
              <span className="ml-2 text-sm font-normal text-gray-500">
                {isPast ? "pogoda z archiwum" : "prognoza"}
              </span>
            )}
          </h3>
          <div className="flex items-center gap-2">
            <button type="button" aria-label="Poprzedni dzień" disabled={!selected || selected <= minDay} onClick={() => selectDay(addDays(selected, -1))} className="rounded-md border border-gray-200 p-2 text-gray-600 hover:bg-gray-50 disabled:opacity-40">
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
            <button type="button" aria-label="Następny dzień" disabled={!selected || selected >= overview.latest_day} onClick={() => selectDay(addDays(selected, 1))} className="rounded-md border border-gray-200 p-2 text-gray-600 hover:bg-gray-50 disabled:opacity-40">
              <FiChevronRight aria-hidden="true" />
            </button>
            {selected !== today && (
              <button type="button" onClick={() => selectDay(today)} className="rounded-md px-2 py-1.5 text-sm font-medium text-emerald-700 hover:bg-emerald-50">Dziś</button>
            )}
          </div>
        </div>

        <p className="-mt-2 mb-3 text-xs text-gray-500">
          Możesz cofnąć się do dowolnego dnia: pogoda jest wtedy z archiwum
          {overview.first_data_day ? `, a od ${formatDate(overview.first_data_day)} są też produkcja i zużycie z Twoich plików` : ""}.
        </p>

        {detailError ? (
          <p role="alert" className="rounded-md bg-amber-50 p-4 text-sm text-amber-800">{detailError}</p>
        ) : !detail ? (
          <ChartSkeleton label="Ładowanie dnia..." className="h-[300px]" />
        ) : (
          <div className={`transition-opacity ${isLoadingDay ? "opacity-60" : ""}`} aria-busy={isLoadingDay}>
            <PvDayChart intervals={detail.intervals} modelLabel={modelLabel} />
            {detail.peak && !isPast && (
              <p className="mt-3 rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-900">
                Najwięcej prądu z paneli: <strong>{formatWindow(detail.peak)}</strong>. Wtedy najlepiej włączać pralkę, zmywarkę albo ładowanie auta.
              </p>
            )}
            <Balance detail={detail} installation={installation} />
            {detail.notes.length > 0 && (
              <ul className="mt-3 space-y-1 text-xs text-gray-500">
                {detail.notes.map((note) => <li key={note}>{note}</li>)}
              </ul>
            )}
          </div>
        )}
      </section>

      <section aria-labelledby="pv-accuracy" className="rounded-lg border border-gray-100 bg-white p-4 shadow-sm md:p-6">
        <h3 id="pv-accuracy" className="mb-1 font-bold text-gray-900">Trafność prognozy</h3>
        <p className="mb-4 text-sm text-gray-600">
          Produkcja z Twoich plików urządzeń obok tego, co model policzył z pogody z tych dni.
        </p>
        {accuracy?.days?.length ? (
          <PvAccuracyChart
            days={accuracy.days}
            onSelect={(day) => {
              selectDay(day);
              daySection.current?.scrollIntoView?.({ behavior: "smooth", block: "start" });
            }}
          />
        ) : (
          <p className="text-sm text-gray-500">
            Nie ma jeszcze dni z produkcją z falownika. <Link to="/upload" className="text-emerald-700 underline">Wgraj plik urządzeń z instalacją PV</Link>, żeby dopasować prognozę do Twojego domu.
          </p>
        )}
      </section>
    </div>
  );
}

export default PvPage;
