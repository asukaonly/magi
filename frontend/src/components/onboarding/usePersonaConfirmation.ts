import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { personasApi } from "../../api/modules/personas";
import type { CustomPersonaDraft } from "./PersonaPreviewChat";

const PERSONA_SETUP_TIMEOUT_MS = 15_000;

class PersonaConfirmationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "PersonaConfirmationError";
  }
}

class PersonaConfirmationCancelledError extends Error {
  constructor() {
    super("Persona confirmation was superseded");
    this.name = "PersonaConfirmationCancelledError";
  }
}

function withTimeout<T>(
  promise: Promise<T>,
  timeoutMs: number,
  message: string,
): Promise<T> {
  let timeoutId: number | undefined;
  const timeoutPromise = new Promise<T>((_, reject) => {
    timeoutId = window.setTimeout(() => {
      reject(new PersonaConfirmationError(message));
    }, timeoutMs);
  });
  return Promise.race([promise, timeoutPromise]).finally(() => {
    if (timeoutId !== undefined) {
      window.clearTimeout(timeoutId);
    }
  });
}

interface UsePersonaConfirmationOptions {
  seedSlug: string | null;
  seedLocale: string;
  selectedCustomPersona: CustomPersonaDraft | null;
}

export function usePersonaConfirmation({
  seedSlug,
  seedLocale,
  selectedCustomPersona,
}: UsePersonaConfirmationOptions) {
  const { t } = useTranslation("onboarding");
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmedFingerprint, setConfirmedFingerprint] = useState<
    string | null
  >(null);
  const requestIdRef = useRef(0);
  const inFlightRef = useRef(false);
  const fingerprint = useMemo(
    () =>
      seedSlug
        ? JSON.stringify([
            seedLocale,
            seedSlug,
            selectedCustomPersona?.personaId ?? null,
            selectedCustomPersona?.config ?? null,
          ])
        : null,
    [seedLocale, seedSlug, selectedCustomPersona],
  );
  const currentFingerprintRef = useRef(fingerprint);
  currentFingerprintRef.current = fingerprint;

  useEffect(
    () => () => {
      requestIdRef.current += 1;
      inFlightRef.current = false;
    },
    [],
  );

  const invalidate = useCallback(() => {
    requestIdRef.current += 1;
    inFlightRef.current = false;
    setConfirming(false);
    setError(null);
    setConfirmedFingerprint(null);
  }, []);

  const confirm = useCallback(
    async (persistSelection?: () => void): Promise<boolean> => {
      const selectedFingerprint = fingerprint;
      const selectedSlug = seedSlug;
      const customDraft = selectedCustomPersona;

      if (!selectedFingerprint || !selectedSlug) {
        requestIdRef.current += 1;
        inFlightRef.current = false;
        setConfirming(false);
        setConfirmedFingerprint(null);
        setError(t("messages.personaSelectionRequired"));
        return false;
      }
      if (confirmedFingerprint === selectedFingerprint) {
        return true;
      }
      if (inFlightRef.current) {
        return false;
      }

      const requestId = ++requestIdRef.current;
      inFlightRef.current = true;
      setConfirming(true);
      setError(null);
      setConfirmedFingerprint(null);

      const assertCurrentRequest = () => {
        if (
          requestId !== requestIdRef.current ||
          currentFingerprintRef.current !== selectedFingerprint
        ) {
          throw new PersonaConfirmationCancelledError();
        }
      };

      const runConfirmation = async () => {
        let personaId: string;
        if (customDraft) {
          persistSelection?.();
          const created = await personasApi.create({
            persona_id: customDraft.personaId,
            slug: customDraft.slug,
            config_json: JSON.stringify(customDraft.config),
            locale: seedLocale,
            reference_dossier: customDraft.referenceDossier,
          });
          assertCurrentRequest();
          if (created?.data?.persona_id !== customDraft.personaId) {
            throw new PersonaConfirmationError(
              t("messages.personaActivationFailed"),
            );
          }
          personaId = customDraft.personaId;
        } else {
          await personasApi.seed(seedLocale);
          assertCurrentRequest();
          const listResult = await personasApi.list();
          assertCurrentRequest();
          const builtin = (listResult.data || []).find(
            (persona) =>
              persona.is_builtin === true &&
              persona.seed_slug === selectedSlug,
          );
          if (!builtin) {
            throw new PersonaConfirmationError(
              t("messages.personaUnavailable"),
            );
          }
          personaId = builtin.persona_id;
        }

        const activated = await personasApi.setActive(personaId);
        assertCurrentRequest();
        if (activated.persona_id !== personaId) {
          throw new PersonaConfirmationError(
            t("messages.personaActivationFailed"),
          );
        }
      };

      try {
        await withTimeout(
          runConfirmation(),
          PERSONA_SETUP_TIMEOUT_MS,
          t("messages.personaSetupTimedOut"),
        );
        assertCurrentRequest();
        inFlightRef.current = false;
        setConfirming(false);
        setError(null);
        setConfirmedFingerprint(selectedFingerprint);
        return true;
      } catch (caught: unknown) {
        if (
          caught instanceof PersonaConfirmationCancelledError ||
          requestId !== requestIdRef.current ||
          currentFingerprintRef.current !== selectedFingerprint
        ) {
          return false;
        }
        requestIdRef.current += 1;
        inFlightRef.current = false;
        setConfirming(false);
        setConfirmedFingerprint(null);
        setError(
          caught instanceof PersonaConfirmationError
            ? caught.message
            : t("messages.personaActivationFailed"),
        );
        return false;
      }
    },
    [
      confirmedFingerprint,
      fingerprint,
      seedLocale,
      seedSlug,
      selectedCustomPersona,
      t,
    ],
  );

  return {
    confirming,
    error,
    invalidate,
    confirm,
  };
}
