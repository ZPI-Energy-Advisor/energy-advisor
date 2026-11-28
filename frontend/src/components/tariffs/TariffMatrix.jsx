import { formatDate } from "../../utils/energyFiles";
import { formatPln } from "../../utils/tariffs";
import { OPERATOR_NAMES, findEntry, formatDifference, isPriced, tariffMatrix } from "../../utils/tariffComparison";
import { CARD_FLUSH } from "../uiStyles";
import UnsupportedTariffs from "./UnsupportedTariffs";

const BADGE = "inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] md:text-xs font-medium";

function EmptyCell({ column }) {
  return (
    <div className="rounded-lg border border-dashed border-gray-200 p-3 text-sm text-gray-400">
      <span className="md:hidden text-xs font-medium text-gray-500">{column}: </span>
      niedostępna
    </div>
  );
}

function TariffCell({ entry, column, chosen, cheapest, reference, onChoose }) {
  const priced = isPriced(entry);
  const difference = entry.key === reference?.key ? null : formatDifference(entry.difference_to_profile, formatPln);
  const referenceName = reference?.is_profile ? "Twojej taryfy" : reference?.label;

  return (
    <button
      type="button"
      onClick={() => onChoose(entry.key)}
      aria-pressed={chosen}
      className={`w-full rounded-lg border p-3 text-left transition-colors ${
        chosen ? "border-emerald-500 ring-2 ring-emerald-200" : "border-gray-200 hover:border-emerald-300"
      } ${cheapest ? "bg-emerald-50" : "bg-white"}`}
    >
      <span className="sr-only">{entry.label}: </span>
      <span className="flex flex-wrap items-center gap-1.5">
        <span className="md:hidden text-xs font-medium text-gray-500">{column}</span>
        {entry.name && <span className="text-[10px] md:text-xs text-gray-500">{entry.name}</span>}
        {entry.is_profile && <span className={`${BADGE} border-blue-200 bg-blue-100 text-blue-800`}>Twoja</span>}
        {cheapest && <span className={`${BADGE} border-emerald-200 bg-emerald-100 text-emerald-800`}>★ Najtańsza</span>}
      </span>
      {priced ? (
        <>
          <span className={`mt-1 block text-lg font-bold ${cheapest ? "text-emerald-700" : "text-gray-900"}`}>
            {formatPln(entry.payable_gross)}
          </span>
          {difference && referenceName && (
            <span className="block text-xs text-gray-600">
              {difference} względem {referenceName}
            </span>
          )}
          <span className="block text-xs text-gray-500">
            za kWh {formatPln(entry.energy_cost_pln)} · opłaty mies. {formatPln(entry.monthly_fees_pln)}
          </span>
          {Number(entry.deposit_amount) > 0 && (
            <span className="block text-xs text-gray-500">
              brutto {formatPln(entry.gross_total)}, depozyt {formatPln(entry.deposit_amount)}
            </span>
          )}
        </>
      ) : (
        <>
          <span className="mt-1 block text-sm font-medium text-gray-500">brak kwoty</span>
          {entry.note && <span className="block text-xs text-gray-500">{entry.note}</span>}
        </>
      )}
    </button>
  );
}

function TariffMatrix({ comparison, chosenKey, onChoose }) {
  const rows = tariffMatrix(comparison.tariffs);
  const hasDynamic = rows.some((row) => row.dynamic);
  const reference = findEntry(comparison, comparison.selected_tariff);
  const columns = hasDynamic ? "md:grid-cols-[8rem_1fr_1fr]" : "md:grid-cols-[8rem_1fr]";
  const unsupported = comparison.unsupported_tariffs ?? [];
  const operatorName = OPERATOR_NAMES[comparison.operator] ?? comparison.operator;

  const cell = (entry, column) =>
    entry ? (
      <TariffCell
        entry={entry}
        column={column}
        chosen={entry.key === chosenKey}
        cheapest={entry.key === comparison.cheapest_tariff}
        reference={isPriced(reference) ? reference : null}
        onChoose={onChoose}
      />
    ) : (
      <EmptyCell column={column} />
    );

  return (
    <section className={`${CARD_FLUSH} mb-6`} aria-labelledby="tariff-matrix-title">
      <div className="border-b border-gray-200 px-4 md:px-5 py-4">
        <h3 id="tariff-matrix-title" className="font-semibold text-gray-900">Porównanie taryf</h3>
        <p className="mt-1 text-xs md:text-sm text-gray-500">
          Kwota do zapłaty brutto za {formatDate(comparison.billed_from)} – {formatDate(comparison.billed_to)}. Kliknij
          taryfę, żeby zobaczyć szczegóły rachunku.
        </p>
      </div>
      <div className="p-3 md:p-4 space-y-3">
        <div className={`hidden md:grid ${columns} gap-3 px-1 text-xs font-medium uppercase tracking-wide text-gray-500`}>
          <span>Grupa</span>
          <span>Zwykła umowa</span>
          {hasDynamic && <span>Cena dynamiczna</span>}
        </div>
        {rows.map((row) => (
          <div key={row.group} role="group" aria-label={`Grupa ${row.group}`} className={`grid gap-2 md:gap-3 ${columns}`}>
            <span className="text-sm font-semibold text-gray-900 md:pt-3">{row.group}</span>
            {cell(row.regular, "Zwykła umowa")}
            {hasDynamic && cell(row.dynamic, "Cena dynamiczna")}
          </div>
        ))}
      </div>
      <UnsupportedTariffs
        intro={`U operatora ${operatorName} są też:`}
        items={unsupported}
        className="border-t border-gray-100 px-4 md:px-5 py-3"
      />
    </section>
  );
}

export default TariffMatrix;
