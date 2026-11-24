import { parsePolicy } from "../utils/privacyPolicy";

// Treść polityki prywatności z backendu (app/legal/privacy_policy.md). Obsługuje tylko to, czego używa
// dokument: nagłówki #/##, akapity, listy „- ” i **pogrubienie**. Tekst idzie do Reacta jako tekst, nie HTML.

function inline(text) {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, index) =>
    part.startsWith("**") && part.endsWith("**") ? (
      <strong key={index}>{part.slice(2, -2)}</strong>
    ) : (
      part
    ),
  );
}

function PrivacyPolicyContent({ markdown, showTitle = true }) {
  return (
    <div className="space-y-3 text-sm leading-relaxed text-gray-700">
      {parsePolicy(markdown).map((block, index) => {
        switch (block.type) {
          case "h1":
            return showTitle ? (
              <h1 key={index} className="text-2xl font-bold text-gray-900">
                {block.text}
              </h1>
            ) : null;
          case "h2":
            return (
              <h2 key={index} className="pt-3 text-lg font-semibold text-gray-900">
                {block.text}
              </h2>
            );
          case "ul":
            return (
              <ul key={index} className="list-disc space-y-1 pl-5">
                {block.items.map((item, itemIndex) => (
                  <li key={itemIndex}>{inline(item)}</li>
                ))}
              </ul>
            );
          default:
            return <p key={index}>{inline(block.text)}</p>;
        }
      })}
    </div>
  );
}

export default PrivacyPolicyContent;
