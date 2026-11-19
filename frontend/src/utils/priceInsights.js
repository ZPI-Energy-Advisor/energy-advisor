// Teksty kart „Jutro najtaniej” i „Jutro najdrożej” z odpowiedzi GET /dynamic-prices/tomorrow/insights.

const priceFormatter = new Intl.NumberFormat("pl-PL", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

// Godziny są już w czasie polskim (z przesunięciem w napisie), więc nie przeliczamy ich przez strefę przeglądarki.
const clock = (isoDateTime) => isoDateTime.slice(11, 16);

export const formatWindowHours = (window) => `${clock(window.start)}–${clock(window.end)}`;

export const formatAveragePrice = (value) => `${priceFormatter.format(value)} zł/kWh`;

export const describeWindow = (window) => `średnio ${formatAveragePrice(window.average_price_pln_kwh)}`;

// Brak cen: przed spodziewaną godziną zapowiadamy ją, po niej mówimy wprost o opóźnieniu.
export const describeUnavailable = (insights, now = new Date()) => {
  const expected = insights.expected_publication_at;
  if (!expected) return "Nie mamy jeszcze cen na jutro.";
  return new Date(expected) > now
    ? `Ceny na jutro pojawią się ok. ${clock(expected)}.`
    : `Cen na jutro jeszcze nie ma, choć zwykle są ok. ${clock(expected)}. Zajrzyj tu trochę później.`;
};

export const describeFlatPrices = (insights) =>
  `Jutro cena prądu prawie się nie zmienia: przez cały dzień ok. ${formatAveragePrice(insights.average_price_pln_kwh)}. ` +
  "Nie ma znaczenia, o której godzinie włączysz urządzenia.";
