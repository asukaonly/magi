export type ChatTurnAdmissionResult<T> =
  | {
    entered: true;
    value: T;
  }
  | {
    entered: false;
    reason:
      | 'in_flight'
      | 'exclusive_action'
      | 'pending_turn'
      | 'invalid_session'
      | 'history_unavailable';
  };

export type ChatTurnSubmissionKind =
  | 'message'
  | 'recall_feedback'
  | 'ask_response'
  | 'inline_skill'
  | 'background_skill';

export type RunWithChatTurnAdmission = <T>(
  sessionId: string,
  kind: ChatTurnSubmissionKind,
  operation: () => Promise<T>,
) => Promise<ChatTurnAdmissionResult<T>>;

export type EnsureChatHistoryReady = (
  sessionId: string,
) => Promise<boolean>;

export type ExistingTurnAdmissionCheck =
  | {
    kind: 'ready';
    stopCurrentIntent?: boolean;
  }
  | {
    kind: 'unconfirmed';
  }
  | {
    kind: 'pending';
    sessionId: string;
    turnId: string;
    input: string;
    timestamp: number;
  };

export class ChatTurnAdmissionCoordinator {
  private readonly activeOperationsBySession = new Map<
    string,
    Promise<void>
  >();
  private readonly exclusiveSessionIds = new Set<string>();
  private readonly pendingTurnIdsBySession = new Map<string, string>();
  private interjectionSettingLoaded = false;
  private allowInterjection = false;

  setInterjectionPolicy({
    loaded,
    allow,
  }: {
    loaded: boolean;
    allow: boolean;
  }): void {
    this.interjectionSettingLoaded = loaded;
    this.allowInterjection = loaded && allow;
  }

  markPendingTurn(sessionId: string, turnId: string): void {
    const normalizedSessionId = String(sessionId || '').trim();
    const normalizedTurnId = String(turnId || '').trim();
    if (!normalizedSessionId || !normalizedTurnId) {
      return;
    }
    this.pendingTurnIdsBySession.set(
      normalizedSessionId,
      normalizedTurnId,
    );
  }

  getPendingTurnId(sessionId: string): string | null {
    const normalizedSessionId = String(sessionId || '').trim();
    if (!normalizedSessionId) {
      return null;
    }
    return this.pendingTurnIdsBySession.get(normalizedSessionId) ?? null;
  }

  clearPendingTurn(sessionId: string, turnId?: string): void {
    const normalizedSessionId = String(sessionId || '').trim();
    const normalizedTurnId = String(turnId || '').trim();
    if (!normalizedSessionId) {
      return;
    }
    if (
      normalizedTurnId
      && this.pendingTurnIdsBySession.get(normalizedSessionId)
        !== normalizedTurnId
    ) {
      return;
    }
    this.pendingTurnIdsBySession.delete(normalizedSessionId);
  }

  clearAllPendingTurns(): void {
    this.pendingTurnIdsBySession.clear();
  }

  private hasBlockingPendingTurn(
    sessionId: string,
    kind: ChatTurnSubmissionKind,
  ): boolean {
    return (
      kind !== 'ask_response'
      && kind !== 'background_skill'
      && this.pendingTurnIdsBySession.has(sessionId)
      && !(
        this.interjectionSettingLoaded
        && this.allowInterjection
      )
    );
  }

  async run<T>(
    sessionId: string,
    kind: ChatTurnSubmissionKind,
    ensureHistoryReady: EnsureChatHistoryReady,
    operation: () => Promise<T>,
  ): Promise<ChatTurnAdmissionResult<T>> {
    const normalizedSessionId = String(sessionId || '').trim();
    if (!normalizedSessionId) {
      return { entered: false, reason: 'invalid_session' };
    }
    if (this.exclusiveSessionIds.has(normalizedSessionId)) {
      return { entered: false, reason: 'exclusive_action' };
    }
    if (this.activeOperationsBySession.has(normalizedSessionId)) {
      return { entered: false, reason: 'in_flight' };
    }
    let releaseActiveOperation: () => void = () => {};
    const activeOperation = new Promise<void>((resolve) => {
      releaseActiveOperation = resolve;
    });
    this.activeOperationsBySession.set(
      normalizedSessionId,
      activeOperation,
    );
    try {
      if (kind !== 'ask_response') {
        let historyReady = false;
        try {
          historyReady = await ensureHistoryReady(normalizedSessionId);
        } catch {
          historyReady = false;
        }
        if (!historyReady) {
          return { entered: false, reason: 'history_unavailable' };
        }
        if (this.hasBlockingPendingTurn(normalizedSessionId, kind)) {
          return { entered: false, reason: 'pending_turn' };
        }
      }
      return {
        entered: true,
        value: await operation(),
      };
    } finally {
      this.activeOperationsBySession.delete(normalizedSessionId);
      releaseActiveOperation();
    }
  }

  async runExclusive<T>(
    sessionId: string,
    operation: () => Promise<T>,
  ): Promise<ChatTurnAdmissionResult<T>> {
    const normalizedSessionId = String(sessionId || '').trim();
    if (!normalizedSessionId) {
      return { entered: false, reason: 'invalid_session' };
    }
    if (this.exclusiveSessionIds.has(normalizedSessionId)) {
      return { entered: false, reason: 'in_flight' };
    }
    this.exclusiveSessionIds.add(normalizedSessionId);
    try {
      const activeOperation = this.activeOperationsBySession.get(
        normalizedSessionId,
      );
      if (activeOperation) {
        await activeOperation;
      }
      return {
        entered: true,
        value: await operation(),
      };
    } finally {
      this.exclusiveSessionIds.delete(normalizedSessionId);
    }
  }
}
