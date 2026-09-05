import { useMemo } from 'react';
import { useNavigate, type NavigateOptions, type To } from 'react-router';
import { asEventHandler } from '@/utils/as-event-handler';

/** UI navigation owns rejected router promises; route errors retain their errorElement. */
export function useAppNavigate() {
  const navigate = useNavigate();
  return useMemo(() => asEventHandler((to: To | number, options?: NavigateOptions) => (
    typeof to === 'number' ? navigate(to) : options === undefined ? navigate(to) : navigate(to, options)
  )), [navigate]);
}
