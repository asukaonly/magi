/** Focus is local to this WebView. Remote playback needs an explicit future owner. */
export class AudioFocus {
  private current: { owner: object; kind: 'recording' | 'playback'; cancel: () => void } | null = null;
  canAutoPlay(): boolean { return this.current === null; }

  acquire(owner: object, kind: 'recording' | 'playback', cancel: () => void): boolean {
    if (this.current?.owner === owner) return true;
    if (kind === 'playback' && this.current?.kind === 'recording') return false;
    const previous = this.current;
    this.current = { owner, kind, cancel };
    previous?.cancel();
    return true;
  }

  release(owner: object): void {
    if (this.current?.owner === owner) this.current = null;
  }
}

export const audioFocus = new AudioFocus();
