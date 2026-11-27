// Wyjaśnienie „jak to liczymy”, zwinięte domyślnie: na ekranie zostaje wniosek, a szczegóły rozwija ten, kogo
// interesują (zamiast akapitów tekstu pod każdym wykresem).
function MoreInfo({ summary = "Jak to liczymy", className = "", children }) {
  return (
    <details className={`group text-sm ${className}`}>
      <summary className="cursor-pointer select-none text-sm font-medium text-emerald-700 hover:text-emerald-800">
        {summary}
      </summary>
      <div className="mt-2 space-y-2 text-sm text-gray-600">{children}</div>
    </details>
  );
}

export default MoreInfo;
