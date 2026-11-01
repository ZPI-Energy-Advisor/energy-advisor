import { SOURCE_TYPE_DEVICES, SOURCE_TYPE_LABELS } from "../utils/energyFiles";

function SourceTypeBadge({ sourceType }) {
  const label = SOURCE_TYPE_LABELS[sourceType];
  if (!label) return null;

  const colors =
    sourceType === SOURCE_TYPE_DEVICES
      ? "bg-sky-50 text-sky-700 border-sky-100"
      : "bg-gray-100 text-gray-600 border-gray-200";

  return (
    <span className={`inline-flex shrink-0 items-center px-1.5 py-0.5 rounded text-[11px] font-medium border ${colors}`}>
      {label}
    </span>
  );
}

export default SourceTypeBadge;
