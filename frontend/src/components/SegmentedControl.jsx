// Przełącznik kilku opcji w stylu przycisków Dashboardu; opcja może być nieaktywna z podpowiedzią.
function SegmentedControl({ options, value, onChange, activeClassName = "text-gray-900", label }) {
  return (
    <div role="group" aria-label={label} className="flex bg-gray-100 p-1 rounded-lg w-full sm:w-auto overflow-x-auto">
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          onClick={() => onChange(option.value)}
          disabled={option.disabled}
          title={option.title}
          aria-pressed={value === option.value}
          className={`flex-1 sm:flex-none px-2 md:px-3 py-1.5 text-xs md:text-sm font-medium rounded-md transition-all whitespace-nowrap disabled:cursor-not-allowed disabled:opacity-50 ${
            value === option.value
              ? `bg-white shadow-sm ${option.activeClassName ?? activeClassName}`
              : "text-gray-500 hover:text-gray-700"
          }`}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

export default SegmentedControl;
