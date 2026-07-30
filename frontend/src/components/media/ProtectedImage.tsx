import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ImgHTMLAttributes,
  type RefObject,
} from 'react';
import {
  getCachedPrivateResourceUrl,
  parsePrivateResourceSource,
  resolvePrivateResourceUrl,
} from '@/api/modules/privateResources';

type ProtectedImageProps = ImgHTMLAttributes<HTMLImageElement> & {
  onProtectedAccessError?: () => void;
  eager?: boolean;
};

function useNearViewport(
  elementRef: RefObject<HTMLImageElement>,
  resourceKey: string,
  enabled: boolean,
  eager: boolean,
): boolean {
  const [nearResourceKey, setNearResourceKey] = useState<string | null>(null);
  const canObserve = enabled && !eager && typeof IntersectionObserver !== 'undefined';

  useEffect(() => {
    if (!canObserve) {
      return;
    }
    const element = elementRef.current;
    if (!element) {
      return;
    }
    setNearResourceKey(null);
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setNearResourceKey(resourceKey);
          observer.disconnect();
        }
      },
      { rootMargin: '480px' },
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, [canObserve, elementRef, resourceKey]);

  return !canObserve || nearResourceKey === resourceKey;
}

export const ProtectedImage = ({
  src,
  loading,
  onError,
  onLoad,
  onProtectedAccessError,
  eager = false,
  ...props
}: ProtectedImageProps) => {
  const imageRef = useRef<HTMLImageElement>(null);
  const descriptor = useMemo(() => parsePrivateResourceSource(src), [src]);
  const descriptorIdentity = descriptor ? JSON.stringify(descriptor) : '';
  const nearViewport = useNearViewport(
    imageRef,
    descriptorIdentity,
    Boolean(descriptor),
    eager,
  );
  const [resolved, setResolved] = useState<{ key: string; url: string } | null>(null);
  const retryCountRef = useRef(0);

  const refresh = useCallback(async (force: boolean): Promise<boolean> => {
    if (!descriptor) {
      return false;
    }
    try {
      const url = await resolvePrivateResourceUrl(descriptor, { force });
      setResolved({ key: descriptorIdentity, url });
      return true;
    } catch {
      onProtectedAccessError?.();
      return false;
    }
  }, [descriptor, descriptorIdentity, onProtectedAccessError]);

  useEffect(() => {
    retryCountRef.current = 0;
    setResolved(null);
  }, [descriptorIdentity, src]);

  useEffect(() => {
    if (!descriptor || !nearViewport) {
      return;
    }
    const cached = getCachedPrivateResourceUrl(descriptor);
    if (cached) {
      setResolved({ key: descriptorIdentity, url: cached });
      return;
    }
    void refresh(false);
  }, [descriptor, descriptorIdentity, nearViewport, refresh]);

  const resolvedSource = descriptor
    ? (resolved?.key === descriptorIdentity ? resolved.url : undefined)
    : src;

  return (
    <img
      {...props}
      ref={imageRef}
      src={resolvedSource}
      loading={loading ?? (eager ? 'eager' : 'lazy')}
      onError={(event) => {
        if (descriptor && retryCountRef.current === 0) {
          retryCountRef.current = 1;
          void refresh(true).then((refreshed) => {
            if (!refreshed) {
              onError?.(event);
            }
          });
          return;
        }
        onError?.(event);
      }}
      onLoad={(event) => {
        retryCountRef.current = 0;
        onLoad?.(event);
      }}
    />
  );
};

export default ProtectedImage;
