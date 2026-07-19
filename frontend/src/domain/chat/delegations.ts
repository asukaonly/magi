const normalizeReferenceValue = (value: unknown): string => (
  typeof value === 'string' ? value.trim() : ''
);
const DELEGATION_ID_PATTERN = /^[0-9a-f]{32}$/;

export interface CodeAgentDelegationReference {
  delegationId: string;
  turnId: string;
  workspacePath: string;
}

export const readCodeAgentDelegations = (
  payload: unknown,
): CodeAgentDelegationReference[] => {
  if (!payload || typeof payload !== 'object') {
    return [];
  }
  const rawReferences = (payload as Record<string, unknown>).code_agent_delegations;
  if (!Array.isArray(rawReferences)) {
    return [];
  }
  const seenDelegationIds = new Set<string>();
  const references: CodeAgentDelegationReference[] = [];
  for (const item of rawReferences) {
    if (!item || typeof item !== 'object' || Array.isArray(item)) {
      continue;
    }
    const record = item as Record<string, unknown>;
    const delegationId = normalizeReferenceValue(record.delegation_id)
      .toLowerCase();
    const turnId = normalizeReferenceValue(record.turn_id);
    const workspacePath = normalizeReferenceValue(record.workspace_path);
    if (
      !DELEGATION_ID_PATTERN.test(delegationId)
      || !turnId
      || !workspacePath
      || seenDelegationIds.has(delegationId)
    ) {
      continue;
    }
    seenDelegationIds.add(delegationId);
    references.push({
      delegationId,
      turnId,
      workspacePath,
    });
  }
  return references;
};
