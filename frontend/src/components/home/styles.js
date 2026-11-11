// Klasy Tailwind wspólne dla komponentów ekranu „Mój dom”.
const BUTTON =
  "inline-flex items-center justify-center gap-1.5 px-3 py-2 rounded text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed";

export const PRIMARY_BUTTON = `${BUTTON} bg-emerald-600 text-white hover:bg-emerald-700`;
export const SECONDARY_BUTTON = `${BUTTON} border border-gray-300 bg-white text-gray-700 hover:bg-gray-50`;
export const CARD = "bg-white border border-gray-200 rounded-lg p-4 md:p-6 shadow-sm";
