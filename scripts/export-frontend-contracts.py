#!/usr/bin/env python3
"""Export response contracts from the production configuration models."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from pydantic.json_schema import GenerateJsonSchema, models_json_schema
from pydantic_core import core_schema

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))


class ResponseJsonSchema(GenerateJsonSchema):
    """Describe full model serialization, including default-valued fields."""

    def field_is_required(
        self,
        field: core_schema.ModelField | core_schema.DataclassField | core_schema.TypedDictField,
        total: bool,
    ) -> bool:
        if self.mode == "serialization" and field["type"] == "model-field":
            return field.get("serialization_exclude_if") is None
        return super().field_is_required(field, total)


def build_contract() -> dict:
    from magi.api.routers.config import config_router
    from magi.api.routers.config_schemas import (
        ConfigResponse,
        OnboardingStatusResponse,
        OnboardingTemplateResponse,
    )
    from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router

    public = _build_public_router(config_router, _PUBLIC_ROUTE_METHODS["config"])
    contracts = {
        ("GET", "/"): ConfigResponse,
        ("PUT", "/"): ConfigResponse,
        ("PUT", "/preferences/language"): ConfigResponse,
        ("GET", "/template"): ConfigResponse,
        ("PUT", "/onboarding-draft"): ConfigResponse,
        ("POST", "/onboarding-complete"): ConfigResponse,
        ("GET", "/onboarding-status"): OnboardingStatusResponse,
        ("GET", "/onboarding-template"): OnboardingTemplateResponse,
    }
    for (method, path), model in contracts.items():
        route = next((route for route in public.routes if route.path == path and method in route.methods), None)
        if route is None or route.response_model is not model:
            raise RuntimeError(f"Configuration contract is not exposed by the public router: {method} {path}")
        if route.response_model_exclude_none or route.response_model_exclude_unset or route.response_model_exclude_defaults:
            raise RuntimeError(f"Configuration response must serialize complete fields: {method} {path}")

    _, document = models_json_schema(
        [(model, "serialization") for model in (
            ConfigResponse, OnboardingStatusResponse, OnboardingTemplateResponse,
        )],
        schema_generator=ResponseJsonSchema,
        ref_template="#/components/schemas/{model}",
    )
    return {
        "openapi": "3.1.0",
        "info": {"title": "Magi configuration response contracts", "version": "1"},
        "paths": {},
        "components": {"schemas": document["$defs"]},
    }


def build_examples() -> dict:
    from magi.api.routers.config_schemas import (
        ConfigResponse,
        LLMProviderConfigModel,
        OnboardingStatusDataModel,
        OnboardingStatusResponse,
        OnboardingTemplateDataModel,
        OnboardingTemplateResponse,
        SystemConfigModel,
    )

    config = SystemConfigModel()
    config.llm.providers["openai"] = LLMProviderConfigModel()
    for selection in config.llm.selections.values():
        selection.provider_id = "openai"
        selection.model = "fixture-model"
    return {
        "config": ConfigResponse(success=True, message="OK", data=config).model_dump(mode="json"),
        "failure": ConfigResponse(success=False, message="Configuration unavailable").model_dump(mode="json"),
        "onboardingStatus": OnboardingStatusResponse(
            success=True, message="OK", data=OnboardingStatusDataModel(completed=False),
        ).model_dump(mode="json"),
        "onboardingTemplate": OnboardingTemplateResponse(
            success=True, message="OK", data=OnboardingTemplateDataModel(config=config),
        ).model_dump(mode="json"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    # Router imports initialize logging. Contract generation must never touch user data.
    from magi.utils.runtime import set_runtime_dir

    with tempfile.TemporaryDirectory(prefix="magi-contract-export-") as runtime_dir:
        set_runtime_dir(runtime_dir)
        outputs = {"frontend-config.json": build_contract(), "frontend-config-examples.json": build_examples()}
    for name, payload in outputs.items():
        target = ROOT / "contracts" / "api" / name
        content = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
        if args.check:
            if not target.exists() or target.read_text(encoding="utf-8") != content:
                print(f"{name} is stale; run scripts/export-frontend-contracts.py", file=sys.stderr)
                return 1
        else:
            target.write_text(content, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
