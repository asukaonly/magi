export type ReasoningPreference = 'auto' | 'fast' | 'deep';

export type ParsedReasoningMessage = {
  message: string;
  preference: ReasoningPreference;
  explicit: boolean;
};

export type ReasoningModifierDecoration = {
  leadingText: string;
  modifierText: string;
  trailingText: string;
};

const REASONING_MODIFIER_PATTERN = /^(\s*)(\/(auto|fast|deep))(?=$|\s)([ \t]*)/i;

export const getReasoningModifierDecoration = (
  input: string,
): ReasoningModifierDecoration | null => {
  const match = input.match(REASONING_MODIFIER_PATTERN);
  if (!match) return null;

  const leadingText = match[1];
  const modifierText = match[2];
  return {
    leadingText,
    modifierText,
    trailingText: input.slice(leadingText.length + modifierText.length),
  };
};

export const parseReasoningMessage = (input: string): ParsedReasoningMessage => {
  const match = input.match(REASONING_MODIFIER_PATTERN);
  if (!match) {
    return {
      message: input,
      preference: 'auto',
      explicit: false,
    };
  }
  return {
    message: input.slice(match[0].length),
    preference: match[3].toLowerCase() as ReasoningPreference,
    explicit: true,
  };
};

export const readReasoningPreference = (
  payload: Record<string, unknown> | null | undefined,
): ReasoningPreference | null => {
  const value = payload?.reasoning_preference;
  return value === 'auto' || value === 'fast' || value === 'deep'
    ? value
    : null;
};

export const applyReasoningModifier = (
  input: string,
  preference: ReasoningPreference,
): string => {
  const message = parseReasoningMessage(input).message.trimStart();
  if (preference === 'auto') {
    return message;
  }
  return `/${preference}${message ? ` ${message}` : ' '}`;
};
