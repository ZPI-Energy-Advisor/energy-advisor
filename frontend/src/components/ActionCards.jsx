import { formatPln } from "../utils/format";

// Najwyżej tyle okresów widać od razu; dłuższą listę (bojler, pompa ciepła) rozwija „pokaż wszystkie”.
const SHOWN_PERIODS = 3;

function Periods({ text }) {
  const periods = text ? text.split(", ") : [];
  if (periods.length <= SHOWN_PERIODS) return <span>{text || "—"}</span>;
  return (
    <details className="group">
      <summary className="cursor-pointer list-none">
        {periods.slice(0, SHOWN_PERIODS).join(", ")}{" "}
        <span className="font-medium text-emerald-700 group-open:hidden">i {periods.length - SHOWN_PERIODS} więcej</span>
      </summary>
      <span>{periods.slice(SHOWN_PERIODS).join(", ")}</span>
    </details>
  );
}

/**
 * Akcje urządzeń jako karty na telefonie, zamiast tabeli z pięcioma kolumnami (plan na jutro, optymalizacja).
 * `items`: { key, name, program, before, after, afterNote, costBefore, costAfter }; `labels` nazywa obie strony,
 * np. { before: "Bez planu", after: "Według planu" }.
 */
function ActionCards({ items, labels, ariaLabel }) {
  return (
    <ul className="space-y-3" aria-label={ariaLabel}>
      {items.map((item) => (
        <li key={item.key} className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
          <p className="font-semibold text-gray-900">
            {item.name}
            {item.program && <span className="font-normal text-gray-500"> · {item.program}</span>}
          </p>
          <dl className="mt-2 space-y-1.5 text-sm">
            <div>
              <dt className="text-xs text-gray-500">{labels.before}</dt>
              <dd className="text-gray-700">
                <Periods text={item.before} />
              </dd>
            </div>
            <div>
              <dt className="text-xs text-gray-500">{labels.after}</dt>
              <dd className="text-gray-900">
                <Periods text={item.after} />
                {item.afterNote && <span className="text-gray-500"> {item.afterNote}</span>}
              </dd>
            </div>
          </dl>
          <p className="mt-2 flex items-center justify-between border-t border-gray-100 pt-2 text-sm">
            <span className="text-gray-500">Koszt</span>
            <span className="tabular-nums">
              <span className="text-gray-500">{formatPln(item.costBefore)}</span>
              <span aria-hidden="true" className="px-1.5 text-gray-400">→</span>
              <span className="sr-only">, po zmianie </span>
              <span className="font-semibold text-gray-900">{formatPln(item.costAfter)}</span>
            </span>
          </p>
        </li>
      ))}
    </ul>
  );
}

export default ActionCards;
