import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { PluginIcon } from '@/components/plugins/PluginIcon';

const SVG_ICON = 'data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciLz4=';

describe('PluginIcon', () => {
  it('renders a validated plugin-owned image', () => {
    render(<PluginIcon iconId={SVG_ICON} />);

    const icon = screen.getByTestId('plugin-icon-asset');
    expect(icon).toHaveAttribute('src', SVG_ICON);
    expect(screen.queryByTestId('plugin-icon-fallback')).not.toBeInTheDocument();
  });

  it('renders any icon exported by the bundled Lucide library', () => {
    const { container } = render(<PluginIcon iconId="lucide:alarm-clock-check" />);

    expect(container.querySelector('.lucide-alarm-clock-check')).toBeInTheDocument();
    expect(container.querySelector('.lucide-activity')).not.toBeInTheDocument();
  });

  it.each([
    ['unknown namespaces', 'brand:github'],
    ['unknown Lucide names', 'lucide:not-a-real-icon'],
    ['unsafe image data', 'data:image/svg+xml,<svg />'],
    ['missing values', null],
  ])('falls back safely for %s', (_label, iconId) => {
    render(<PluginIcon iconId={iconId} />);

    expect(screen.getByTestId('plugin-icon-fallback')).toHaveClass('lucide-activity');
    expect(screen.queryByTestId('plugin-icon-asset')).not.toBeInTheDocument();
  });
});
