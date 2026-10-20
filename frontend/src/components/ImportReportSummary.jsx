import { FiAlertTriangle, FiCheckCircle } from "react-icons/fi";
import { formatCount } from "../utils/energyFiles";

const ROWS = ["wiersz", "wiersze", "wierszy"];

const RESOLUTION_LABELS = {
  15: "odczyty co 15 min",
  60: "odczyty godzinowe",
};

function ImportReportSummary({ report }) {
  if (!report) return null;

  const skipped = report.skipped_rows ?? { count: 0, examples: [] };
  const notListed = skipped.count - skipped.examples.length;

  return (
    <div className="mt-6 text-left bg-white border border-emerald-100 rounded-lg p-4 md:p-5 text-sm">
      <h4 className="font-bold text-gray-900 mb-3">Raport z importu</h4>
      <dl className="grid grid-cols-1 sm:grid-cols-[auto_1fr] gap-x-6 gap-y-1.5 text-gray-700">
        <dt className="text-gray-500">Rozpoznany format</dt>
        <dd className="font-medium">{report.format_label}</dd>
        <dt className="text-gray-500">Zaimportowano</dt>
        <dd className="font-medium">
          {formatCount(report.rows_imported, ROWS)} z {report.rows_total}
          {RESOLUTION_LABELS[report.resolution_minutes] && ` · ${RESOLUTION_LABELS[report.resolution_minutes]}`}
        </dd>
        {report.rows_ignored > 0 && (
          <>
            <dt className="text-gray-500">Pominięto</dt>
            <dd>{formatCount(report.rows_ignored, ROWS)} z energią oddaną do sieci lub innym rodzajem energii</dd>
          </>
        )}
      </dl>

      {skipped.count > 0 ? (
        <div className="mt-4 p-3 rounded-lg bg-amber-50 text-amber-900">
          <p className="flex items-center gap-2 font-medium">
            <FiAlertTriangle className="shrink-0" />
            Odrzucono {formatCount(skipped.count, ["błędny wiersz", "błędne wiersze", "błędnych wierszy"])}
          </p>
          <ul className="mt-2 space-y-1">
            {skipped.examples.map((example) => (
              <li key={example.row}>
                <span className="font-medium">Wiersz {example.row}:</span> {example.reason}
              </li>
            ))}
          </ul>
          {notListed > 0 && <p className="mt-1 text-amber-700">…i {formatCount(notListed, ROWS)} więcej.</p>}
        </div>
      ) : (
        <p className="mt-4 flex items-center gap-2 text-emerald-700">
          <FiCheckCircle className="shrink-0" /> Wszystkie wiersze z poborem energii zostały zaimportowane.
        </p>
      )}
    </div>
  );
}

export default ImportReportSummary;
