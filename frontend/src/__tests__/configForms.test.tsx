import { SimpleForm as Form } from '../components/onboarding/simple-form';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import LLMForm from '../components/config-forms/LLMForm';
import MemoryForm from '../components/config-forms/MemoryForm';

describe('config forms', () => {
  it('quick mode should hide optional llm fields', () => {
    render(
      <Form>
        <LLMForm quickMode />
      </Form>
    );
    expect(screen.queryByText('Base URL')).not.toBeInTheDocument();
    expect(screen.queryByText('Custom Name')).not.toBeInTheDocument();
  });

  it('memory form disables l2-l5 when l1 off', async () => {
    const user = userEvent.setup();
    render(
      <Form initialValues={{ memory_layers: { L1: { enabled: true } } }}>
        <MemoryForm />
      </Form>
    );
    const l1Switch = screen.getAllByRole('checkbox')[0];
    await user.click(l1Switch);
    expect(await screen.findByText('L2-L5 依赖 L1')).toBeInTheDocument();
  });
});
