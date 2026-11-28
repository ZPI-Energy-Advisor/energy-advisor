import MoreInfo from "../MoreInfo";

// Taryfy operatora, których kalkulator jeszcze nie liczy, z powodem pod „Dlaczego?”: podpowiedź po najechaniu
// nie działa na telefonie, a rozwinięcie działa i na komputerze, i na telefonie.
function UnsupportedTariffs({ intro, items, className = "" }) {
  if (!items?.length) return null;
  return (
    <div className={`text-xs text-gray-500 ${className}`}>
      <p>
        {intro} {items.map((item) => item.code).join(", ")}. Jeszcze ich nie liczymy.
      </p>
      {items.some((item) => item.reason) && (
        <MoreInfo summary="Dlaczego?" className="mt-1">
          <ul className="space-y-1 text-xs">
            {items.map((item) => (
              <li key={item.code}>
                <span className="font-medium text-gray-700">{item.code}</span>
                {item.reason && `: ${item.reason}`}
              </li>
            ))}
          </ul>
        </MoreInfo>
      )}
    </div>
  );
}

export default UnsupportedTariffs;
