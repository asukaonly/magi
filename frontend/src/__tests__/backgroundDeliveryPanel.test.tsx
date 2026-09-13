import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
const { status, retry, get, post, streams, recover } = vi.hoisted(() => ({ status:vi.fn(),retry:vi.fn(),get:vi.fn(),post:vi.fn(),streams:vi.fn(),recover:vi.fn() }));
vi.mock('@/runtime/background-delivery', async (original) => ({...await original<typeof import('@/runtime/background-delivery')>(),readBackgroundDeliveryStatus:status,retryBackgroundDelivery:retry,readBackgroundStreams:streams,recoverBackgroundStream:recover}));
vi.mock('@/api/client', () => ({api:{get,post},unwrapGatewayPayload:(r:unknown)=>r}));
vi.mock('react-i18next', () => ({useTranslation:()=>({t:(key:string,values?:Record<string,unknown>)=>values ? `${key}:${values.pending}:${values.failed}` : key})}));
import { BackgroundDeliveryPanel } from '@/components/connections/BackgroundDeliveryPanel';

beforeEach(()=>{
  vi.resetAllMocks();streams.mockResolvedValue([]);recover.mockResolvedValue(undefined);
  status.mockResolvedValue({queue:{pending:3,failed:1,bytes:40,next_retry_at_ms:0,last_error:'handler_not_replay_safe'},notification_read_ids:[]});
  get.mockResolvedValue({pending:2,failed:1,streams:[],truncated:false});retry.mockResolvedValue(undefined);post.mockResolvedValue({ok:true});
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
  finish?.({pending:0,failed:0,streams:[],truncated:false});
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

it('targets one stream and requires a second click before discarding its records', async () => {
  const row = { stream:'photos',connection_id:'conn-one',plugin_target:'photos',pending:2,failed:1,
    oldest_at_ms:10,attempts:2,next_retry_at_ms:20,last_error:'permission_required' };
  streams.mockResolvedValue([row]);
  render(<BackgroundDeliveryPanel />);
  fireEvent.click(await screen.findByRole('button', {name:'connections.delivery.retryStream'}));
  await waitFor(() => expect(recover).toHaveBeenCalledWith('photos', false));
  await waitFor(() => expect(screen.getByRole('button', {name:'connections.delivery.discard'})).toBeEnabled());
  fireEvent.click(screen.getByRole('button', {name:'connections.delivery.discard'}));
  expect(recover).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole('button', {name:'connections.delivery.confirmDiscard'}));
  await waitFor(() => expect(recover).toHaveBeenLastCalledWith('photos', true));
  expect(post).not.toHaveBeenCalled();
});
