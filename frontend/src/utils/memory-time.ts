export const formatMemoryTimeRange = (
  start: number | null | undefined,
  end: number | null | undefined,
  locale: string
): string => {
  if (!start && !end) {
    return '';
  }
  const formatter = new Intl.DateTimeFormat(locale, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
  if (start && end) {
    return `${formatter.format(new Date(start * 1000))} - ${formatter.format(new Date(end * 1000))}`;
  }
  return formatter.format(new Date((start ?? end ?? 0) * 1000));
};
