import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { InstallStepper } from '@/components/plugins/InstallStepper';

describe('InstallStepper', () => {
  it('renders one row per step with animated active progress', () => {
    render(
      <InstallStepper
        steps={[
          { id: 'install', status: 'done' },
          { id: 'enable', status: 'running' },
          { id: 'sync', status: 'pending' },
          { id: 'memory', status: 'pending' },
        ]}
        labels={{ install: 'Install', enable: 'Enable', sync: 'Sync', memory: 'Memory' }}
      />,
    );
    expect(screen.getByText('Install')).toBeInTheDocument();
    expect(screen.getByTestId('step-install-status')).toHaveAttribute('data-status', 'done');
    expect(screen.getByTestId('step-enable')).toHaveAttribute('aria-current', 'step');
    expect(screen.getByTestId('step-enable-status')).toHaveAttribute('data-status', 'running');
    expect(screen.getByTestId('step-enable-status').firstElementChild).toHaveClass('animate-spin');
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '36');
  });

  it('renders the error glyph and applies the destructive tone', () => {
    render(
      <InstallStepper
        steps={[{ id: 'enable', status: 'error' }]}
        labels={{ install: 'Install', enable: 'Enable', sync: 'Sync', memory: 'Memory' }}
      />,
    );
    const row = screen.getByTestId('step-enable');
    expect(screen.getByTestId('step-enable-status')).toHaveAttribute('data-status', 'error');
    expect(row.className).toContain('text-destructive');
  });

  it('renders step details for memory progress counts', () => {
    render(
      <InstallStepper
        steps={[
          { id: 'sync', status: 'done' },
          { id: 'memory', status: 'running' },
        ]}
        labels={{ install: 'Install', enable: 'Enable', sync: 'Sync', memory: 'Memory' }}
        details={{ memory: '已整理 12 / 40 条，剩余 28 条' }}
      />,
    );

    expect(screen.getAllByText('已整理 12 / 40 条，剩余 28 条').length).toBeGreaterThan(0);
  });
});
