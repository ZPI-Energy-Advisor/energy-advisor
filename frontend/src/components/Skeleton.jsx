// Szare zarysy treści na czas ładowania zamiast samego tekstu: układ strony stoi od razu, a dane
// podmieniają zarys bez skoku. Tekst dla czytników ekranu zostaje (role="status", sr-only).
const PULSE = "animate-pulse rounded-lg bg-gray-200/70";
// Stałe wysokości słupków, żeby zarys wykresu wyglądał jak wykres, a nie jak pusty prostokąt.
const BARS = [35, 52, 44, 68, 58, 80, 62, 74, 48, 56, 40, 66, 54, 72, 46, 60];

export function ChartSkeleton({ label, className = "h-[280px] md:h-[400px]" }) {
  return (
    <div role="status" className={`flex w-full items-end gap-1.5 px-2 pb-6 md:gap-2 ${className}`}>
      <span className="sr-only">{label}</span>
      {BARS.map((height, index) => (
        <div key={index} aria-hidden="true" className="flex-1 animate-pulse rounded-t bg-gray-200/70" style={{ height: `${height}%` }} />
      ))}
    </div>
  );
}

export function PageSkeleton({ label, cards = 3, maxWidth = "max-w-6xl" }) {
  return (
    <div role="status" className={`mx-auto ${maxWidth} pb-12`}>
      <span className="sr-only">{label}</span>
      <div aria-hidden="true" className="mb-6 flex flex-wrap items-center justify-between gap-4 border-b border-gray-200 pb-4 md:mb-8">
        <div className={`h-7 w-56 ${PULSE}`} />
        <div className="flex gap-2">
          <div className={`h-9 w-56 rounded-full ${PULSE}`} />
          <div className={`h-9 w-44 rounded-full ${PULSE}`} />
        </div>
      </div>
      {cards > 0 && (
        <div aria-hidden="true" className="mb-8 grid grid-cols-1 gap-4 sm:grid-cols-3 md:gap-6">
          {Array.from({ length: cards }, (_, index) => (
            <div key={index} className="rounded-lg border border-gray-100 bg-white p-5 md:p-6">
              <div className={`h-4 w-2/3 ${PULSE}`} />
              <div className={`mt-4 h-8 w-1/2 ${PULSE}`} />
              <div className={`mt-3 h-3 w-3/4 ${PULSE}`} />
            </div>
          ))}
        </div>
      )}
      <div aria-hidden="true" className="rounded-lg border border-gray-100 bg-white p-4 md:p-6">
        <div className={`mb-6 h-5 w-48 ${PULSE}`} />
        <ChartSkeleton label="" />
      </div>
    </div>
  );
}
