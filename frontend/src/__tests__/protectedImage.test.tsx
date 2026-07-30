import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const privateResourceMocks = vi.hoisted(() => ({
  getCachedPrivateResourceUrl: vi.fn(),
  parsePrivateResourceSource: vi.fn(),
  resolvePrivateResourceUrl: vi.fn(),
}));

vi.mock('@/api/modules/privateResources', () => ({
  getCachedPrivateResourceUrl: privateResourceMocks.getCachedPrivateResourceUrl,
  parsePrivateResourceSource: privateResourceMocks.parsePrivateResourceSource,
  resolvePrivateResourceUrl: privateResourceMocks.resolvePrivateResourceUrl,
}));

import { ProtectedImage } from '@/components/media/ProtectedImage';

const DESCRIPTOR = {
  kind: 'timeline_asset' as const,
  asset_ref: 'photo-library://day/photo.jpg',
};
const PRIVATE_SOURCE =
  'http://127.0.0.1:43123/api/timeline/asset/photo-library%3A%2F%2Fday%2Fphoto.jpg';

type ObserverRecord = {
  callback: IntersectionObserverCallback;
  observe: ReturnType<typeof vi.fn>;
  disconnect: ReturnType<typeof vi.fn>;
};

const originalIntersectionObserver = globalThis.IntersectionObserver;
let observers: ObserverRecord[] = [];

class MockIntersectionObserver {
  readonly root = null;
  readonly rootMargin = '480px';
  readonly thresholds = [0];
  readonly observe = vi.fn();
  readonly unobserve = vi.fn();
  readonly disconnect = vi.fn();
  readonly takeRecords = vi.fn(() => []);

  constructor(callback: IntersectionObserverCallback) {
    observers.push({
      callback,
      observe: this.observe,
      disconnect: this.disconnect,
    });
  }
}

describe('ProtectedImage', () => {
  beforeEach(() => {
    observers = [];
    privateResourceMocks.getCachedPrivateResourceUrl.mockReset();
    privateResourceMocks.getCachedPrivateResourceUrl.mockReturnValue(null);
    privateResourceMocks.parsePrivateResourceSource.mockReset();
    privateResourceMocks.parsePrivateResourceSource.mockImplementation((source?: string) => (
      source === PRIVATE_SOURCE ? DESCRIPTOR : null
    ));
    privateResourceMocks.resolvePrivateResourceUrl.mockReset();
    Object.defineProperty(globalThis, 'IntersectionObserver', {
      configurable: true,
      writable: true,
      value: MockIntersectionObserver,
    });
  });

  afterEach(() => {
    Object.defineProperty(globalThis, 'IntersectionObserver', {
      configurable: true,
      writable: true,
      value: originalIntersectionObserver,
    });
  });

  it('waits until a private image is near the viewport before requesting access', async () => {
    privateResourceMocks.resolvePrivateResourceUrl.mockResolvedValue(
      'http://127.0.0.1:43123/private/photo?ticket=nearby',
    );

    render(<ProtectedImage src={PRIVATE_SOURCE} alt="private photo" />);

    const image = screen.getByRole('img', { name: 'private photo' });
    expect(image).not.toHaveAttribute('src');
    expect(privateResourceMocks.resolvePrivateResourceUrl).not.toHaveBeenCalled();
    expect(observers).toHaveLength(1);
    expect(observers[0].observe).toHaveBeenCalledWith(image);

    act(() => {
      const bounds = image.getBoundingClientRect();
      observers[0].callback(
        [{
          boundingClientRect: bounds,
          intersectionRatio: 1,
          intersectionRect: bounds,
          isIntersecting: true,
          rootBounds: null,
          target: image,
          time: 0,
        }],
        {} as IntersectionObserver,
      );
    });

    await waitFor(() => {
      expect(image).toHaveAttribute(
        'src',
        'http://127.0.0.1:43123/private/photo?ticket=nearby',
      );
    });
    expect(privateResourceMocks.resolvePrivateResourceUrl).toHaveBeenCalledWith(
      DESCRIPTOR,
      { force: false },
    );
  });

  it('forces one fresh grant when loading a protected URL fails', async () => {
    const onError = vi.fn();
    privateResourceMocks.resolvePrivateResourceUrl
      .mockResolvedValueOnce('http://127.0.0.1:43123/private/photo?ticket=expired')
      .mockResolvedValueOnce('http://127.0.0.1:43123/private/photo?ticket=fresh');

    render(
      <ProtectedImage
        src={PRIVATE_SOURCE}
        alt="retry photo"
        eager
        onError={onError}
      />,
    );

    const image = screen.getByRole('img', { name: 'retry photo' });
    await waitFor(() => {
      expect(image).toHaveAttribute(
        'src',
        'http://127.0.0.1:43123/private/photo?ticket=expired',
      );
    });

    fireEvent.error(image);
    await waitFor(() => {
      expect(image).toHaveAttribute(
        'src',
        'http://127.0.0.1:43123/private/photo?ticket=fresh',
      );
    });
    expect(privateResourceMocks.resolvePrivateResourceUrl).toHaveBeenLastCalledWith(
      DESCRIPTOR,
      { force: true },
    );

    fireEvent.error(image);
    expect(privateResourceMocks.resolvePrivateResourceUrl).toHaveBeenCalledTimes(2);
    expect(onError).toHaveBeenCalledTimes(1);
  });

  it('passes external images through without requesting private access', () => {
    const source = 'https://images.example/avatar.png';

    render(<ProtectedImage src={source} alt="external avatar" />);

    expect(screen.getByRole('img', { name: 'external avatar' })).toHaveAttribute('src', source);
    expect(privateResourceMocks.resolvePrivateResourceUrl).not.toHaveBeenCalled();
    expect(observers).toHaveLength(0);
  });
});
