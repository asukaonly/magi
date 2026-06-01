function _detectPlatformString(): string {
  if (typeof navigator === 'undefined') {
    return '';
  }
  const platformHint = (navigator as Navigator & { userAgentData?: { platform?: string } })
    .userAgentData?.platform;
  return String(platformHint || navigator.platform || navigator.userAgent || '');
}

export function isMacPlatform(): boolean {
  return /mac/i.test(_detectPlatformString());
}

export function isWindowsPlatform(): boolean {
  const p = _detectPlatformString();
  return /win/i.test(p) && !/mac/i.test(p);
}

export function isLinuxPlatform(): boolean {
  const p = _detectPlatformString();
  return /linux/i.test(p) && !/android/i.test(p);
}
