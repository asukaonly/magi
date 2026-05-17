export function isMacPlatform(): boolean {
  if (typeof navigator === 'undefined') {
    return false;
  }
  const platform = String((navigator as Navigator & { userAgentData?: { platform?: string } }).userAgentData?.platform || navigator.platform || '');
  if (/mac/i.test(platform)) {
    return true;
  }
  return /mac/i.test(navigator.userAgent || '');
}
