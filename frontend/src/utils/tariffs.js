// Taryfa, względem której liczymy koszty, gdy nie znamy taryfy użytkownika z profilu.
export const DEFAULT_COMPARISON_TARIFF = "G11";

export const comparisonTariffCode = (currentTariff) =>
  currentTariff?.code ?? DEFAULT_COMPARISON_TARIFF;
