import { render, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { ModelDownloadProgress, type DownloadProgress } from '@/components/settings/ModelDownloadProgress';
import { readModelDownloadStatus } from '@/api/modules/model-download';

vi.mock('react-i18next', () => ({ useTranslation: () => ({
  i18n: { language: 'en' },
  t: (key: string, options?: Record<string, unknown>) => options ? `${key} ${JSON.stringify(options)}` : key,
}) }));

const progress: DownloadProgress = {
  phase: 'downloading', downloaded_bytes: 96 * 1024 ** 2, total_bytes: 228 * 1024 ** 2,
  speed_bps: 3.2 * 1024 ** 2, eta_seconds: 41, files_completed: 1, total_files: 2,
};

it('shows measured bytes, rate and remaining time while downloading', () => {
  render(<ModelDownloadProgress progress={progress} />);
  expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '42');
  expect(screen.getByText('96 MB / 228 MB')).toBeInTheDocument();
  expect(screen.getByText('3.2 MB/s')).toBeInTheDocument();
  expect(screen.getByText(/modelDownload.remaining/)).toBeInTheDocument();
});

it('keeps unknown progress indeterminate and hides an unreliable estimate', () => {
  const view = render(<ModelDownloadProgress progress={null} active />);
  expect(screen.getByRole('progressbar')).not.toHaveAttribute('aria-valuenow');
  expect(screen.queryByText(/%/)).not.toBeInTheDocument();
  view.rerender(<ModelDownloadProgress progress={{ ...progress, eta_seconds: null, speed_bps: 0 }} />);
  expect(screen.queryByText(/remaining/)).not.toBeInTheDocument();
  expect(screen.queryByText(/MB\/s/)).not.toBeInTheDocument();
});

it('distinguishes verification from availability and collapses completed transfers', () => {
  const view = render(<ModelDownloadProgress progress={{ ...progress, phase: 'verifying', downloaded_bytes: progress.total_bytes!, speed_bps: 0, eta_seconds: null }} />);
  expect(screen.getByRole('status')).toHaveTextContent('modelDownload.phases.verifying');
  expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '100');
  view.rerender(<ModelDownloadProgress progress={{ ...progress, phase: 'completed' }} />);
  expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
});

it('retains cancelled bytes and shows small-file activity without hiding slow rates', () => {
  const view = render(<ModelDownloadProgress progress={{ ...progress, speed_bps: 1024, total_files: 376 }} />);
  expect(screen.getByText('1 KB/s')).toBeInTheDocument();
  expect(screen.getByText(/modelDownload.files/)).toBeInTheDocument();
  view.rerender(<ModelDownloadProgress progress={{ ...progress, phase: 'cancelled', speed_bps: 0, eta_seconds: null }} />);
  expect(screen.getByRole('status')).toHaveTextContent('modelDownload.phases.cancelled');
  expect(screen.getByText('96 MB / 228 MB')).toBeInTheDocument();
});

it('rejects malformed progress at the network boundary', () => {
  const status = { model_id: 'model', status: 'downloading', download: progress, error: null };
  expect(readModelDownloadStatus(status)).toEqual(status);
  expect(() => readModelDownloadStatus({ ...status, download: { ...progress, downloaded_bytes: -1 } })).toThrow();
  expect(() => readModelDownloadStatus({ ...status, download: { ...progress, phase: 'pretending' } })).toThrow();
  expect(() => readModelDownloadStatus({ model_id: 'model', status: 'downloading', progress_pct: 10 })).toThrow();
});
