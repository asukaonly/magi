export type SkillArgumentParseResult =
  | { ok: true; arguments: string[] }
  | { ok: false };

const countHintArguments = (hint: string | null | undefined): number => (
  (String(hint || '').match(/<[^<>]+>|\[[^[\]]+\]/g) || []).length
);

const parseQuotedArguments = (input: string): SkillArgumentParseResult => {
  const argumentsList: string[] = [];
  let current = '';
  let quote: "'" | '"' | null = null;
  let escaping = false;

  for (const character of input) {
    if (escaping) {
      current += character;
      escaping = false;
      continue;
    }
    if (character === '\\' && quote !== "'") {
      escaping = true;
      continue;
    }
    if (quote) {
      if (character === quote) {
        quote = null;
      } else {
        current += character;
      }
      continue;
    }
    if (character === "'" || character === '"') {
      quote = character;
      continue;
    }
    if (/\s/.test(character)) {
      if (current) {
        argumentsList.push(current);
        current = '';
      }
      continue;
    }
    current += character;
  }

  if (quote || escaping) {
    return { ok: false };
  }
  if (current) {
    argumentsList.push(current);
  }
  return { ok: true, arguments: argumentsList };
};

export const parseSkillArguments = (
  argsText: string,
  argumentHint: string | null | undefined,
): SkillArgumentParseResult => {
  const trimmed = String(argsText || '').trim();
  if (!trimmed) {
    return { ok: true, arguments: [] };
  }
  const parsed = parseQuotedArguments(trimmed);
  if (!parsed.ok) {
    return parsed;
  }
  if (countHintArguments(argumentHint) === 1) {
    return parsed.arguments.length <= 1
      ? parsed
      : { ok: true, arguments: [trimmed] };
  }
  return parsed;
};
