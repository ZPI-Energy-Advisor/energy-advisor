// Podział treści polityki (Markdown z app/legal/privacy_policy.md) na bloki: nagłówki #/##, akapity i listy „- ”.
export function parsePolicy(markdown) {
  const blocks = [];
  let paragraph = null;
  let list = null;

  const close = () => {
    if (paragraph) blocks.push({ type: "p", text: paragraph.join(" ") });
    if (list) blocks.push({ type: "ul", items: list });
    paragraph = null;
    list = null;
  };

  for (const rawLine of markdown.split("\n")) {
    const line = rawLine.trimEnd();
    if (!line.trim()) {
      close();
    } else if (line.startsWith("# ") || line.startsWith("## ")) {
      close();
      blocks.push({ type: line.startsWith("# ") ? "h1" : "h2", text: line.replace(/^#+ /, "") });
    } else if (line.startsWith("- ")) {
      if (paragraph) close();
      list = list ?? [];
      list.push(line.slice(2));
    } else if (list && /^\s+/.test(line)) {
      // Dalszy ciąg punktu listy (wcięta linia).
      list[list.length - 1] += ` ${line.trim()}`;
    } else {
      if (list) close();
      paragraph = paragraph ?? [];
      paragraph.push(line.trim());
    }
  }
  close();
  return blocks;
}
