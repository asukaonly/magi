import i18n from 'i18next';
import { toast } from 'sonner';

/**
 * Adapt an operation to a callback whose caller does not await its result.
 * Operations still own validation, pending state, cancellation and expected
 * failures. This boundary reports unexpected failures instead of dropping them.
 * Invoke synchronously so React event.currentTarget remains available.
 */
export function asEventHandler<Args extends unknown[]>(
  operation: (...args: Args) => unknown,
): (...args: Args) => void {
  return (...args) => {
    const report = (error: unknown) => {
      console.error('UI operation failed', error);
      toast.error(i18n.t('common.operationFailed', { ns: 'app' }));
    };
    try {
      const result = operation(...args);
      Promise.resolve(result).catch(report);
    } catch (error) {
      report(error);
    }
  };
}
