import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
const { status, retry, get, post } = vi.hoisted(() => ({ status:vi.fn(),retry:vi.fn(),get:vi.fn(),post:vi.fn() }));
vi.mock('@/runtime/background-delivery', () => ({readBackgroundDeliveryStatus:status,retryBackgroundDelivery:retry}));
vi.mock('@/api/client', () => ({api:{get,post},unwrapGatewayPayload:(r:unknown)=>r}));
vi.mock('react-i18next', () => ({useTranslation:()=>({t:(key:string,values?:Record<string,unknown>)=>values ? `${key}:${values.pending}:${values.failed}` : key})}));
import { BackgroundDeliveryPanel } from '@/components/connections/BackgroundDeliveryPanel';

beforeEach(()=>{
  vi.resetAllMocks();
  status.mockResolvedValue({queue:{pending:3,failed:1,bytes:40,next_retry_at_ms:0,last_error:'handler_not_replay_safe'},notification_read_ids:[]});
  get.mockResolvedValue({pending:2,failed:1});retry.mockResolvedValue(undefined);post.mockResolvedValue({ok:true});
});

it('retains local queue visibility when the center is offline', async ()=>{
  get.mockRejectedValue(new Error('offline'));
  render(<BackgroundDeliveryPanel />);
  expect(await screen.findByText('connections.delivery.outbox:3:1')).toBeInTheDocument();
  expect(screen.getByText('connections.delivery.serverUnavailable')).toBeInTheDocument();
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});

it('shows the local queue before a stalled server request completes', async ()=>{
  let finish: ((value: unknown) => void) | undefined;
  get.mockImplementation(() => new Promise((resolve) => { finish=resolve; }));
  render(<BackgroundDeliveryPanel />);
  expect(await screen.findByText('connections.delivery.outbox:3:1')).toBeInTheDocument();
  expect(screen.getByText('common.loading')).toBeInTheDocument();
  finish?.({pending:0,failed:0});
  expect(await screen.findByText('connections.delivery.inbox:0:0')).toBeInTheDocument();
});

it('retries quarantined client and server work and releases the pending button', async ()=>{
  render(<BackgroundDeliveryPanel />);
  const button=await screen.findByRole('button',{name:'connections.delivery.retry'});
  fireEvent.click(button);
  await waitFor(()=>expect(post).toHaveBeenCalledWith('/delivery/retry',{}));
  expect(retry).toHaveBeenCalledTimes(1);
  await waitFor(()=>expect(button).toBeEnabled());
});

it('shows a failure without erasing the queue counts', async ()=>{
  retry.mockRejectedValue(new Error('disk unavailable'));
  render(<BackgroundDeliveryPanel />);
  fireEvent.click(await screen.findByRole('button',{name:'connections.delivery.retry'}));
  expect(await screen.findByRole('alert')).toHaveTextContent('connections.delivery.failed');
  expect(screen.getByText('connections.delivery.outbox:3:1')).toBeInTheDocument();
});
