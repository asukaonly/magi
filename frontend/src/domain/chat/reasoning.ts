export type ReasoningPreference = 'auto' | 'fast' | 'deep';

export type ParsedReasoningMessage = {
  message: string;
  preference: ReasoningPreference;
  explicit: boolean;
};

const REASONING_MODIFIER_PATTERN = /^\s*\/(auto|fast|deep)(?=$|\s)[ \t]*/i;

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
    preference: match[1].toLowerCase() as ReasoningPreference,
    explicit: true,
  };
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
