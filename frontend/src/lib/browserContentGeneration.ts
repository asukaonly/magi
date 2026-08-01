let browserContentGeneration = 0;

export type BrowserContentGeneration = number;

export const captureBrowserContentGeneration = (): BrowserContentGeneration => (
  browserContentGeneration
);

export const isBrowserContentGenerationCurrent = (
  generation: BrowserContentGeneration,
): boolean => generation === browserContentGeneration;

export const advanceBrowserContentGeneration = (): BrowserContentGeneration => {
  browserContentGeneration += 1;
  return browserContentGeneration;
};
