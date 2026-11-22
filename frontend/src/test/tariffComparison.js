const cycle = (overrides = {}) => ({
  cycle_start: "2026-01-01T00:00:00",
  cycle_end: "2026-02-28T00:00:00",
  days_billed: 31,
  days_in_cycle: 59,
  active_energy_kwh: 300,
  active_energy_net: 150,
  excise_net: 1.5,
  variable_network_net: 90,
  quality_net: 10,
  renewable_net: 2,
  cogeneration_net: 1,
  fixed_network_net: 20,
  subscription_net: 1.5,
  capacity_net: 12,
  transition_net: 0.5,
  trade_fee_net: 0,
  net_total: 288.5,
  vat: 66.36,
  gross_total: 354.86,
  ...overrides,
});

export const entry = (key, payable, overrides = {}) => {
  const dynamic = key.endsWith("-dynamic");
  const group = key.replace("-dynamic", "");
  return {
    key,
    label: dynamic ? `${group} z ceną dynamiczną` : group,
    name: dynamic ? "Oferta dynamiczna" : null,
    type: dynamic ? "dynamiczna" : "strefowa",
    tariff_code: dynamic ? "dynamic" : group,
    distribution_group: group,
    is_profile: false,
    note: null,
    billing_cycle_months: dynamic ? 1 : 2,
    payable_gross: payable,
    gross_total: payable,
    deposit_amount: 0,
    deposit_applied: 0,
    energy_cost_pln: payable == null ? null : Math.round((payable - 50) * 100) / 100,
    monthly_fees_pln: payable == null ? null : 50,
    monthly_fee_gross: 25,
    cost_breakdown: payable == null ? null : { energy: 100, distribution: 60, fees: 10, vat: payable - 220 },
    cycles: payable == null ? [] : [cycle({ gross_total: payable })],
    difference_to_profile: null,
    ...overrides,
  };
};

export const comparisonOf = (entries, overrides = {}) => {
  const selected = overrides.selected_tariff ?? entries.find((item) => item.is_profile)?.key ?? "G11";
  const reference = entries.find((item) => item.key === selected)?.payable_gross;
  const priced = entries.filter((item) => item.payable_gross != null);
  const cheapest = priced.reduce((best, item) => (best && best.payable_gross <= item.payable_gross ? best : item), null);
  return {
    source_id: "f1",
    source_name: "dom.csv",
    source_type: "meter",
    date_from: "2026-01-01",
    date_to: "2026-01-31",
    billed_from: "2026-01-01",
    billed_to: "2026-01-31",
    all_tariffs: true,
    operator: "TAURON",
    from_profile: true,
    profile_tariff: selected,
    selected_tariff: selected,
    selection_note: null,
    billing_cycle_months: 2,
    pv_mode: null,
    annual_consumption: { annual_kwh: 3650, days: 31, scaled: true, consumption_kwh: 310 },
    cheapest_tariff: cheapest?.key ?? null,
    tariffs: entries.map((item) => ({
      ...item,
      difference_to_profile:
        reference == null || item.payable_gross == null ? null : Math.round((item.payable_gross - reference) * 100) / 100,
    })),
    warnings: [],
    unsupported_tariffs: [],
    ...overrides,
  };
};

export const COMPARISON = comparisonOf([
  entry("G11", 400, { is_profile: true }),
  entry("G12", 350),
  entry("G13", null, { note: "Brak stawek abonamentowej dla okresu 2 mies." }),
  entry("G11-dynamic", 380),
  entry("G12-dynamic", 330),
]);

export const PV_COMPARISON = comparisonOf(
  [
    entry("G11", 250, { is_profile: true, gross_total: 300, deposit_amount: 80, deposit_applied: 50 }),
    entry("G12", 220, { gross_total: 260, deposit_amount: 70, deposit_applied: 40 }),
  ],
  { pv_mode: "net_billing" },
);

export const chartRow = (hour, prices) => ({
  hour,
  kwh: 1,
  ...Object.fromEntries(Object.entries(prices).flatMap(([key, price]) => [[`price_${key}`, price], [`cost_${key}`, price]])),
});
