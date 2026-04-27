const MARKDOWN_DOCUMENT_FENCE = /^\s*```(?:markdown|md)\s*\n([\s\S]*?)\n```\s*/i;
const MARKDOWN_DOCUMENT_HINT = /^\s{0,3}(#{1,6}\s|[-*]\s|>\s|\|.+\|)/m;

export const normalizeAssistantMarkdownContent = (content: string): string => {
  const text = String(content || '');
  const match = text.match(MARKDOWN_DOCUMENT_FENCE);
  if (!match) {
    return text;
  }

  const body = String(match[1] || '').trim();
  if (!MARKDOWN_DOCUMENT_HINT.test(body)) {
    return text;
  }

  const rest = text.slice(match[0].length).trim();
  return rest ? `${body}\n\n${rest}` : body;
};