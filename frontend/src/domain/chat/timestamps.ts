const SECOND_BASED_EPOCH_THRESHOLD = 1e11;

export const normalizeChatTimestamp = (
  value: unknown,
  fallback: number = Date.now(),
): number => {
  const numericValue = Number(value);
  if (!Number.isFinite(numericValue) || numericValue <= 0) {
    return fallback;
  }
  if (numericValue < SECOND_BASED_EPOCH_THRESHOLD) {
    return Math.round(numericValue * 1000);
  }
  return Math.round(numericValue);
};

export const formatChatClockTime = (
  value: unknown,
  language: string,
): string => {
  const timestamp = normalizeChatTimestamp(value, 0);
  if (!timestamp) {
    return '';
  }
  return new Date(timestamp).toLocaleTimeString(
    language === 'en' ? 'en-US' : 'zh-CN',
    {
      hour: '2-digit',
      minute: '2-digit',
    },
  );
};
