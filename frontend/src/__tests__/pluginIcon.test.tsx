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

  it('renders Photo Library with a dedicated photo icon instead of the generic image fallback', () => {
    render(<PluginIcon iconId="custom:photo-library" />);

    expect(screen.getByTestId('plugin-icon-photo-library')).toBeInTheDocument();
    expect(screen.queryByTestId('plugin-icon-fallback')).not.toBeInTheDocument();
  });

  it('resolves GitHub Activity to the GitHub brand icon when the registry icon is missing', () => {
    render(<PluginIcon iconId="brand:github" />);

    expect(screen.getByTestId('plugin-icon-github')).toBeInTheDocument();
    expect(screen.queryByTestId('plugin-icon-fallback')).not.toBeInTheDocument();
  });
});
