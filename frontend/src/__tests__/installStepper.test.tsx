import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { InstallStepper } from '@/components/plugins/InstallStepper';

describe('InstallStepper', () => {
  it('renders one row per step with the right status glyph', () => {
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
    expect(screen.getByTestId('step-install')).toHaveTextContent('✓');
    expect(screen.getByTestId('step-enable')).toHaveTextContent('…');
    expect(screen.getByTestId('step-sync')).toHaveTextContent('·');
  });

  it('renders the error glyph and applies the destructive tone', () => {
    render(
      <InstallStepper
        steps={[{ id: 'enable', status: 'error' }]}
        labels={{ install: 'Install', enable: 'Enable', sync: 'Sync', memory: 'Memory' }}
      />,
    );
    const row = screen.getByTestId('step-enable');
    expect(row).toHaveTextContent('×');
    expect(row.className).toContain('text-destructive');
  });
});
