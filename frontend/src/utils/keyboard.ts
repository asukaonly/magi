import type React from 'react';

export const shouldSubmitOnEnter = (
  event: Pick<React.KeyboardEvent, 'key' | 'shiftKey' | 'nativeEvent'>,
  isComposing: boolean,
): boolean => {
  const nativeEvent = event.nativeEvent;
  const keyCode = Number(nativeEvent?.keyCode || 0);
  return (
    event.key === 'Enter' &&
    !event.shiftKey &&
    !isComposing &&
    !nativeEvent?.isComposing &&
    keyCode !== 229
  );
};
