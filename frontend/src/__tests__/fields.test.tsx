import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { SelectField } from '@/components/config-forms/fields';

describe('SelectField', () => {
  it('does not render an empty placeholder option when empty selection is disallowed', async () => {
    const user = userEvent.setup();

    render(
      <SelectField
        value="manual"
        onChange={vi.fn()}
        allowEmpty={false}
        placeholder="请选择"
        options={[
          { label: 'Manual', value: 'manual' },
          { label: 'Interval', value: 'interval' },
        ]}
      />
    );

    await user.click(screen.getByRole('button'));

    expect(screen.queryByRole('button', { name: '请选择' })).not.toBeInTheDocument();
  });

  it('does not allow selecting disabled options', async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();

    render(
      <SelectField
        value="ready"
        onChange={onChange}
        allowEmpty={false}
        options={[
          { label: 'Ready', value: 'ready' },
          { label: 'Unavailable', value: 'unavailable', disabled: true },
        ]}
      />
    );

    await user.click(screen.getByRole('button'));

    const disabledOption = screen.getByRole('button', { name: 'Unavailable' });
    expect(disabledOption).toBeDisabled();

    await user.click(disabledOption);
    expect(onChange).not.toHaveBeenCalled();
  });
});
