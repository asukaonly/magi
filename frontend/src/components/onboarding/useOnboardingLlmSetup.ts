import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { configApi } from "../../api/modules/config";
import type {
  LLMConfig,
  TestLLMProviderConnectionRequest,
} from "../../api/modules/config";
import { cloneLLMConfig, cloneProvider } from "../config-forms/llm-form-state";
import type { LLMConnectionTestState } from "./LLMSetupStep";

interface LlmConnectionTestTarget {
  fingerprint: string;
  request: TestLLMProviderConnectionRequest;
}

const EMPTY_CONNECTION_TEST_STATE: LLMConnectionTestState = {
  loading: false,
  error: null,
  result: null,
};

function buildConnectionTestTarget(
  value: LLMConfig,
): LlmConnectionTestTarget | null {
  const providerId = String(value.selections?.core?.provider_id || "").trim();
  const model = String(value.selections?.core?.model || "").trim();
  const sourceProvider = providerId ? value.providers?.[providerId] : undefined;
  if (!providerId || !model || !sourceProvider) {
    return null;
  }

  const provider = cloneProvider(sourceProvider);
  const apiKey = provider.services.chat.api_key || provider.api_key || "";
  const baseUrl = provider.services.chat.base_url || provider.base_url || "";
  provider.api_key = provider.api_key || apiKey;
  provider.base_url = provider.base_url || baseUrl;
  provider.services.chat.api_key = apiKey;
  provider.services.chat.base_url = baseUrl;

  return {
    fingerprint: JSON.stringify([
      providerId,
      provider.provider_type,
      provider.provider_plan || "",
      provider.api_format,
      model,
      apiKey,
      baseUrl,
    ]),
    request: {
      provider_id: providerId,
      provider,
      model,
    },
  };
}

export function useOnboardingLlmSetup(initialValue: LLMConfig) {
  const { t } = useTranslation("onboarding");
  const [value, setValue] = useState<LLMConfig>(() =>
    cloneLLMConfig(initialValue),
  );
  const [valid, setValid] = useState(false);
  const [connectionTestState, setConnectionTestState] =
    useState<LLMConnectionTestState>(EMPTY_CONNECTION_TEST_STATE);
  const [validatedFingerprint, setValidatedFingerprint] = useState<
    string | null
  >(null);
  const [connectionConfigPending, setConnectionConfigPending] =
    useState(false);
  const requestIdRef = useRef(0);
  const target = useMemo(() => buildConnectionTestTarget(value), [value]);
  const currentFingerprint = target?.fingerprint || "";
  const currentFingerprintRef = useRef(currentFingerprint);
  currentFingerprintRef.current = currentFingerprint;

  useEffect(
    () => () => {
      requestIdRef.current += 1;
    },
    [],
  );

  const change = useCallback(
    (next: LLMConfig) => {
      const nextFingerprint =
        buildConnectionTestTarget(next)?.fingerprint || "";
      if (nextFingerprint !== currentFingerprintRef.current) {
        requestIdRef.current += 1;
        setValidatedFingerprint(null);
        setConnectionTestState(EMPTY_CONNECTION_TEST_STATE);
      }
      setValue(next);
    },
    [],
  );

  const testConnection = useCallback(
    async (force = false): Promise<boolean> => {
      const currentTarget = buildConnectionTestTarget(value);
      if (!currentTarget) {
        setValidatedFingerprint(null);
        setConnectionTestState({
          loading: false,
          error: t("llm.providerConfiguration.testModelRequired"),
          result: null,
        });
        return false;
      }

      if (
        !force &&
        validatedFingerprint === currentTarget.fingerprint &&
        connectionTestState.result
      ) {
        return true;
      }

      const requestId = ++requestIdRef.current;
      setValidatedFingerprint(null);
      setConnectionTestState({
        loading: true,
        error: null,
        result: null,
      });
      try {
        const result = await configApi.testLLMProviderConnection(
          currentTarget.request,
        );
        if (
          requestId !== requestIdRef.current ||
          currentFingerprintRef.current !== currentTarget.fingerprint
        ) {
          return false;
        }
        setValidatedFingerprint(currentTarget.fingerprint);
        setConnectionTestState({
          loading: false,
          error: null,
          result,
        });
        return true;
      } catch (error: unknown) {
        if (
          requestId !== requestIdRef.current ||
          currentFingerprintRef.current !== currentTarget.fingerprint
        ) {
          return false;
        }
        setConnectionTestState({
          loading: false,
          error:
            error instanceof Error && error.message
              ? error.message
              : t("llm.providerConfiguration.testFailed"),
          result: null,
        });
        return false;
      }
    },
    [connectionTestState.result, t, validatedFingerprint, value],
  );

  return {
    value,
    valid,
    connectionTestState,
    connectionConfigPending,
    change,
    setValid,
    setConnectionConfigPending,
    testConnection,
  };
}
