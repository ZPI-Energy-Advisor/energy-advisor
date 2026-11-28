import { useState } from "react";
import { formatDate } from "../../utils/energyFiles";
import { describeBreakdown, formatPln } from "../../utils/tariffs";
import {
  CYCLE_COMPONENTS,
  CYCLE_GROUPS,
  PV_MODE_LABELS,
  cycleGroupTitle,
  cycleGroupValue,
  isPriced,
} from "../../utils/tariffComparison";
import { formatKwh } from "../../utils/format";
import { CARD, TABLE, TABLE_HEAD, TD_NUMBER, TH } from "../uiStyles";
import MoreInfo from "../MoreInfo";
import { useIsPhone } from "../../hooks/useMediaQuery";

const CELL = TD_NUMBER;
const HEAD = TH;

function Metric({ label, value, accent = false }) {
  return (
    <div className="rounded-lg border border-gray-200 p-3">
      <p className="text-xs font-medium uppercase tracking-wide text-gray-500">{label}</p>
      <p className={`mt-1 text-lg font-bold ${accent ? "text-emerald-700" : "text-gray-900"}`}>{value}</p>
    </div>
  );
}

function Fact({ label, children }) {
  return (
    <div>
      <dt className="text-xs text-gray-500">{label}</dt>
      <dd className="mt-0.5 text-sm font-semibold text-gray-900">{children}</dd>
    </div>
  );
}

function CyclesTable({ cycles }) {
  const [expanded, setExpanded] = useState(false);
  const isPhone = useIsPhone();
  const withTradeFee = cycles.some((cycle) => Number(cycle.trade_fee_net) > 0);
  const columns = expanded
    ? CYCLE_COMPONENTS.filter(([key]) => key !== "trade_fee_net" || withTradeFee).map(([key, label]) => ({
        key,
        label,
        value: (cycle) => cycle[key],
      }))
    : CYCLE_GROUPS.map((group) => ({
        key: group.key,
        label: group.label,
        title: cycleGroupTitle(group),
        value: (cycle) => cycleGroupValue(cycle, group),
      }));

  return (
    <div className="mt-5">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h4 className="text-sm font-semibold text-gray-900">Okresy rozliczeniowe</h4>
        <button
          type="button"
          onClick={() => setExpanded((current) => !current)}
          aria-expanded={expanded}
          className="text-sm font-medium text-emerald-700 hover:underline"
        >
          {expanded ? "Pokaż mniej składników" : "Pokaż wszystkie składniki"}
        </button>
      </div>
      {isPhone ? (
        // Na telefonie okres i kwota brutto w wierszu, składniki po rozwinięciu: tabela z wieloma kolumnami
        // wymagałaby przesuwania w bok.
        <ul className="divide-y divide-gray-100 rounded-lg border border-gray-200" aria-label="Okresy rozliczeniowe">
          {cycles.map((cycle) => (
            <li key={cycle.cycle_start}>
              <details className="group px-3 py-2.5">
                <summary className="flex cursor-pointer list-none items-start justify-between gap-3 text-sm">
                  <span className="font-medium text-gray-900">
                    {formatDate(cycle.cycle_start)} – {formatDate(cycle.cycle_end)}
                    {cycle.days_billed < cycle.days_in_cycle && (
                      <span className="block text-xs font-normal text-gray-500">
                        opłaty miesięczne za {cycle.days_billed} z {cycle.days_in_cycle} dni
                      </span>
                    )}
                  </span>
                  <span className="shrink-0 text-right font-semibold tabular-nums text-gray-900">
                    {formatPln(cycle.gross_total)}
                    <span className="block text-xs font-normal text-emerald-700 group-open:hidden">składniki</span>
                  </span>
                </summary>
                <dl className="mt-2 space-y-1 text-sm">
                  {columns.map((column) => (
                    <div key={column.key} className="flex justify-between gap-3">
                      <dt className="text-gray-500">{column.label}</dt>
                      <dd className="tabular-nums text-gray-800">{formatPln(column.value(cycle))}</dd>
                    </div>
                  ))}
                </dl>
              </details>
            </li>
          ))}
        </ul>
      ) : (
      <div className="overflow-x-auto rounded-lg border border-gray-200">
        <table className={TABLE}>
          <thead className={TABLE_HEAD}>
            <tr>
              <th scope="col" className={`${HEAD} text-left`}>Okres</th>
              {columns.map((column) => (
                <th key={column.key} scope="col" className={`${HEAD} text-right`} title={column.title}>
                  {column.label}
                </th>
              ))}
              <th scope="col" className={`${HEAD} text-right`}>Brutto</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {cycles.map((cycle) => (
              <tr key={cycle.cycle_start}>
                <td className="whitespace-nowrap px-3 md:px-4 py-3 text-sm font-medium text-gray-900">
                  {formatDate(cycle.cycle_start)} – {formatDate(cycle.cycle_end)}
                  {cycle.days_billed < cycle.days_in_cycle && (
                    <p className="text-xs font-normal text-gray-500">
                      opłaty miesięczne za {cycle.days_billed} z {cycle.days_in_cycle} dni
                    </p>
                  )}
                </td>
                {columns.map((column) => (
                  <td key={column.key} className={CELL}>
                    {formatPln(column.value(cycle))}
                  </td>
                ))}
                <td className={`${CELL} font-semibold`}>{formatPln(cycle.gross_total)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      )}
      {columns.some((column) => column.title) && (
        <MoreInfo summary="Co zawierają kolumny" className="mt-2 [&_summary]:text-xs">
          <ul className="space-y-1 text-xs">
            {columns.filter((column) => column.title).map((column) => (
              <li key={column.key}>
                <span className="font-medium text-gray-700">{column.label}</span>: {column.title}
              </li>
            ))}
          </ul>
        </MoreInfo>
      )}
      <p className="mt-2 text-xs text-gray-500">Składniki netto, VAT i kwota brutto okresu przed potrąceniem depozytu.</p>
    </div>
  );
}

function TariffBillDetails({ entry, comparison }) {
  const annual = comparison.annual_consumption;
  const withDeposit = Boolean(comparison.pv_mode) || Number(entry.deposit_amount) > 0;
  const title = [entry.label, entry.name].filter(Boolean).join(" · ");

  return (
    <section className={CARD} aria-labelledby="tariff-details-title">
      <h3 id="tariff-details-title" className="font-semibold text-gray-900">
        Szczegóły rachunku: {title}
      </h3>
      {!isPriced(entry) ? (
        <p className="mt-3 text-sm text-gray-600">{entry.note ?? "Tej taryfy nie udało się policzyć dla wybranego okresu."}</p>
      ) : (
        <>
          <div className={`mt-4 grid gap-3 ${withDeposit ? "grid-cols-2 lg:grid-cols-4" : "grid-cols-1 sm:grid-cols-2"}`}>
            <Metric label="Do zapłaty" value={formatPln(entry.payable_gross)} accent />
            {withDeposit ? (
              <>
                <Metric label="Rachunek brutto" value={formatPln(entry.gross_total)} />
                <Metric label="Depozyt" value={formatPln(entry.deposit_amount)} />
                <Metric label="Potrącono z energii czynnej" value={formatPln(entry.deposit_applied)} />
              </>
            ) : (
              <Metric label="Rachunek brutto" value={formatPln(entry.gross_total)} />
            )}
          </div>
          <dl className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {annual && <Fact label="Zużycie w okresie">{formatKwh(annual.consumption_kwh)}</Fact>}
            <Fact label="Tryb PV">{comparison.pv_mode ? PV_MODE_LABELS[comparison.pv_mode] ?? comparison.pv_mode : "Brak instalacji PV"}</Fact>
            {annual && (
              <Fact label="Roczne zużycie (próg opłaty mocowej)">
                {formatKwh(annual.annual_kwh)}
                {annual.scaled && (
                  <span className="block text-xs font-normal text-gray-500">przeskalowane z {annual.days} dni danych</span>
                )}
              </Fact>
            )}
            <Fact label="Okres rozliczeniowy">{entry.billing_cycle_months} mies.</Fact>
            {entry.monthly_fee_gross != null && <Fact label="Opłaty miesięczne">{formatPln(entry.monthly_fee_gross)} / mies.</Fact>}
            {entry.active_energy_gross != null && (
              <Fact label="Energia czynna brutto">{formatPln(entry.active_energy_gross)}</Fact>
            )}
          </dl>
          <p className="mt-4 text-sm text-gray-700">
            Za kWh <span className="font-semibold">{formatPln(entry.energy_cost_pln)}</span>
            {entry.cost_breakdown && (
              <span className="text-gray-500">
                {" "}
                ({describeBreakdown(entry.cost_breakdown, formatPln)}
                {Number(entry.deposit_applied) > 0 && ` · minus depozyt ${formatPln(entry.deposit_applied)}`})
              </span>
            )}
            , opłaty miesięczne <span className="font-semibold">{formatPln(entry.monthly_fees_pln)}</span>.
          </p>
          {entry.cycles?.length > 0 && <CyclesTable cycles={entry.cycles} />}
        </>
      )}
    </section>
  );
}

export default TariffBillDetails;
