import { useEffect, useState } from 'react';

import { APP_EVENTS, subscribeToAppEvent } from '@/constants/events';

/** Remount content pages after their backing data has been removed. */
export function useMemoryClearEpoch(): number {
  const [epoch, setEpoch] = useState(0);

  useEffect(() => subscribeToAppEvent(
    APP_EVENTS.MEMORY_CLEARED,
    () => setEpoch((current) => current + 1),
  ), []);

  return epoch;
}
