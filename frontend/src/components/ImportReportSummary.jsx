import { FiAlertTriangle, FiCheckCircle } from "react-icons/fi";
import { formatCount, formatDateRange } from "../utils/energyFiles";
import IncompleteDaysNotice from "./IncompleteDaysNotice";

const RESOLUTION_LABELS = {
  15: "odczyty co 15 min",
  60: "odczyty godzinowe",
};

// Raport liczy wiersze pliku CSV albo akcje pliku urządzeń (JSON), zależnie od report.unit.
const UNITS = {
  row: {
    imported: ["wiersz", "wiersze", "wierszy"],
    more: ["wiersz", "wiersze", "wierszy"],
    rejected: ["błędny wiersz", "błędne wiersze", "błędnych wierszy"],
    example: (example) => `Wiersz ${example.row}:`,
    allImported: "Wszystkie wiersze z poborem i oddaniem energii zostały zaimportowane.",
    showResolution: true,
  },
  action: {
    imported: ["akcję", "akcje", "akcji"],
    more: ["akcja", "akcje", "akcji"],
    rejected: ["błędną akcję", "błędne akcje", "błędnych akcji"],
    example: (example) => `Akcja ${example.row}${example.action_id ? ` (${example.action_id})` : ""}:`,
    allImported: "Wszystkie akcje urządzeń zostały zaimportowane.",
    showResolution: false,
  },
};

const DEVICES = ["urządzenie", "urządzenia", "urządzeń"];
const DAYS = ["dzień", "dni", "dni"];

const formatKwh = (value) => `${value.toLocaleString("pl-PL", { maximumFractionDigits: 2 })} kWh`;

function ImportReportSummary({ report, fileName, statistics }) {
  if (!report) return null;

  const unit = UNITS[report.unit] ?? UNITS.row;
  // Tylko plik urządzeń: zużycie urządzeń i produkcja PV przed autokonsumpcją.
  const devices = report.devices;
  const hasGridTotals = report.grid_import_kwh !== undefined;
  const skipped = report.skipped_rows ?? { count: 0, examples: [] };
  const notListed = skipped.count - skipped.examples.length;
  const resolution = unit.showResolution && RESOLUTION_LABELS[report.resolution_minutes];

  return (
    <div className="mt-6 text-left bg-white border border-emerald-100 rounded-lg p-4 md:p-5 text-sm">
      <h4 className="font-bold text-gray-900 mb-3">Raport z importu</h4>
      <dl className="grid grid-cols-1 sm:grid-cols-[auto_1fr] gap-x-6 gap-y-1.5 text-gray-700">
        {fileName && (
          <>
            <dt className="text-gray-500">Plik</dt>
            <dd className="font-medium break-all">{fileName}</dd>
          </>
        )}
        <dt className="text-gray-500">Rozpoznany format</dt>
        <dd className="font-medium">{report.format_label}</dd>
        {statistics?.data_start && (
          <>
            <dt className="text-gray-500">Zakres dat</dt>
            <dd>
              {formatDateRange(statistics)} · {formatCount(statistics.days_analyzed, DAYS)}
            </dd>
          </>
        )}
        <dt className="text-gray-500">Zaimportowano</dt>
        <dd className="font-medium">
          {formatCount(report.rows_imported, unit.imported)} z {report.rows_total}
          {resolution && ` · ${resolution}`}
        </dd>
        {report.rows_ignored > 0 && (
          <>
            <dt className="text-gray-500">Pominięto</dt>
            <dd>{formatCount(report.rows_ignored, UNITS.row.imported)} z innym rodzajem energii (np. bierną)</dd>
          </>
        )}
        {hasGridTotals && (
          <>
            <dt className="text-gray-500">Sieć</dt>
            <dd>
              pobór {formatKwh(report.grid_import_kwh)}
              {report.grid_export_kwh > 0 && ` · oddanie ${formatKwh(report.grid_export_kwh)}`}
            </dd>
          </>
        )}
        {devices && (
          <>
            <dt className="text-gray-500">Urządzenia</dt>
            <dd>
              {formatCount(devices.devices_count, DEVICES)} · {devices.categories.join(", ")}
            </dd>
            <dt className="text-gray-500">Energia</dt>
            <dd>
              zużycie urządzeń {formatKwh(devices.consumption_kwh)}
              {devices.pv_production_kwh > 0 && ` · produkcja PV ${formatKwh(devices.pv_production_kwh)}`}
            </dd>
          </>
        )}
      </dl>

      <IncompleteDaysNotice statistics={statistics} className="mt-4" />

      {skipped.count > 0 ? (
        <div className="mt-4 p-3 rounded-lg bg-amber-50 text-amber-900">
          <p className="flex items-center gap-2 font-medium">
            <FiAlertTriangle className="shrink-0" />
            Odrzucono {formatCount(skipped.count, unit.rejected)}
          </p>
          <ul className="mt-2 space-y-1">
            {skipped.examples.map((example) => (
              <li key={example.row}>
                <span className="font-medium">{unit.example(example)}</span> {example.reason}
              </li>
            ))}
          </ul>
          {notListed > 0 && <p className="mt-1 text-amber-700">…i {formatCount(notListed, unit.more)} więcej.</p>}
        </div>
      ) : (
        <p className="mt-4 flex items-center gap-2 text-emerald-700">
          <FiCheckCircle className="shrink-0" /> {unit.allImported}
        </p>
      )}
    </div>
  );
}

export default ImportReportSummary;
