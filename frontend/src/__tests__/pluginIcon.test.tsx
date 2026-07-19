import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { PluginIcon } from '@/components/plugins/PluginIcon';

describe('PluginIcon', () => {
  it('renders Chrome as a multicolor brand icon', () => {
    render(<PluginIcon iconId="brand:googlechrome" />);

    const icon = screen.getByTestId('plugin-icon-googlechrome');

    expect(icon.querySelector('[data-icon-color="red"]')).toBeInTheDocument();
    expect(icon.querySelector('[data-icon-color="yellow"]')).toBeInTheDocument();
    expect(icon.querySelector('[data-icon-color="green"]')).toBeInTheDocument();
    expect(icon.querySelector('[data-icon-color="blue"]')).toBeInTheDocument();
  });

  it('renders Apple Photos with its multicolor flower icon', () => {
    render(<PluginIcon iconId="custom:apple-photos" />);

    expect(screen.getByTestId('plugin-icon-apple-photos')).toBeInTheDocument();
    expect(screen.queryByTestId('plugin-icon-fallback')).not.toBeInTheDocument();
  });

  it('renders Codex with its dedicated mark', () => {
    render(<PluginIcon iconId="custom:codex" />);

    expect(screen.getByTestId('plugin-icon-codex')).toBeInTheDocument();
    expect(screen.queryByTestId('plugin-icon-fallback')).not.toBeInTheDocument();
  });

  it('renders Claude Code with its brand icon', () => {
    render(<PluginIcon iconId="brand:claudecode" />);

    expect(screen.getByTestId('plugin-icon-claudecode')).toBeInTheDocument();
    expect(screen.queryByTestId('plugin-icon-fallback')).not.toBeInTheDocument();
  });

  it('renders Microsoft Edge with its dedicated multicolor icon', () => {
    render(<PluginIcon iconId="custom:microsoft-edge" />);

    expect(screen.getByTestId('plugin-icon-microsoft-edge')).toBeInTheDocument();
    expect(screen.queryByTestId('plugin-icon-fallback')).not.toBeInTheDocument();
  });

  it.each([
    ['lucide:calendar-days', 'lucide-calendar-days'],
    ['lucide:chart-no-axes-column', 'lucide-chart-no-axes-column'],
    ['lucide:gamepad-2', 'lucide-gamepad-2'],
    ['lucide:images', 'lucide-images'],
    ['lucide:scan', 'lucide-scan'],
  ])('renders the supported icon %s', (iconId, className) => {
    const { container } = render(<PluginIcon iconId={iconId} />);

    expect(container.querySelector(`.${className}`)).toBeInTheDocument();
    expect(container.querySelector('.lucide-activity')).not.toBeInTheDocument();
  });

  it('resolves GitHub Activity to the GitHub brand icon when the registry icon is missing', () => {
    render(<PluginIcon iconId="brand:github" />);

    expect(screen.getByTestId('plugin-icon-github')).toBeInTheDocument();
    expect(screen.queryByTestId('plugin-icon-fallback')).not.toBeInTheDocument();
  });
});
