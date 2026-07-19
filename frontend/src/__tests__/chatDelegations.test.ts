import { describe, expect, it } from 'vitest';

import { readCodeAgentDelegations } from '@/domain/chat/delegations';
import delegationContract from '../../../contracts/chat/code_agent_delegation_reference.json';

describe('chat delegation references', () => {
  it('parses the shared backend and frontend contract fixture', () => {
    expect(readCodeAgentDelegations(delegationContract.payload)).toEqual([
      {
        delegationId: '0123456789abcdef0123456789abcdef',
        turnId: 'turn-contract-code-agent',
        workspacePath: '/workspace-at-execution',
      },
    ]);
  });

  it('accepts complete references, trims values, and deduplicates by delegation id', () => {
    const firstDelegationId = 'A'.repeat(32);
    const secondDelegationId = 'B'.repeat(32);
    expect(readCodeAgentDelegations({
      code_agent_delegations: [
        {
          delegation_id: ` ${firstDelegationId} `,
          turn_id: ' turn-1 ',
          workspace_path: ' /tmp/workspace-1 ',
        },
        {
          delegation_id: firstDelegationId.toLowerCase(),
          turn_id: 'conflicting-turn',
          workspace_path: '/tmp/conflicting-workspace',
        },
        {
          delegation_id: secondDelegationId,
          turn_id: 'turn-2',
          workspace_path: '/tmp/workspace-2',
        },
      ],
    })).toEqual([
      {
        delegationId: firstDelegationId.toLowerCase(),
        turnId: 'turn-1',
        workspacePath: '/tmp/workspace-1',
      },
      {
        delegationId: secondDelegationId.toLowerCase(),
        turnId: 'turn-2',
        workspacePath: '/tmp/workspace-2',
      },
    ]);
  });

  it('rejects legacy, incomplete, and incorrectly typed references', () => {
    expect(readCodeAgentDelegations({
      code_agent_delegation_ids: ['legacy-id'],
      background_task_id: 'background-id',
      code_agent_delegations: [
        null,
        'delegation-1',
        {
          delegation_id: 'c'.repeat(32),
          turn_id: '',
          workspace_path: '/tmp/workspace',
        },
        {
          delegation_id: 'd'.repeat(32),
          turn_id: 'turn-2',
          workspace_path: 42,
        },
        ...[
          '<script>alert(1)</script>',
          '../delegation',
          'g'.repeat(32),
          'e'.repeat(31),
          'f'.repeat(33),
          '１２３４５６７８９０abcdef0123456789abcdef',
        ].map((delegationId) => ({
          delegation_id: delegationId,
          turn_id: 'turn-malicious',
          workspace_path: '/tmp/workspace',
        })),
      ],
    })).toEqual([]);
  });
});
