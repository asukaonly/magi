"""Host-owned wording for grounded facts consumed by memory projections."""

from __future__ import annotations

from ...i18n import effective_app_language_code
from .phase1_models import L2Phase1FactClaim

_PREDICATE_WORDING = {
    "LIKES": ("喜欢", "likes"),
    "DISLIKES": ("不喜欢", "dislikes"),
    "INTERESTED_IN": ("关注", "is interested in"),
    "REAL_NAME": ("姓名是", "has the name"),
    "BIRTH_DATE": ("生日是", "has the birth date"),
    "BIRTH_YEAR": ("出生年份是", "has the birth year"),
    "STATED_AGE": ("自述年龄是", "reports an age of"),
    "AGE": ("自述年龄是", "reports an age of"),
    "PREFERRED_FORM_OF_ADDRESS": ("希望被称为", "prefers to be called"),
    "DISALLOWED_FORM_OF_ADDRESS": ("不希望被称为", "does not want to be called"),
    "PREFERRED_COMMUNICATION_STYLE": ("偏好的沟通方式是", "prefers the communication style"),
    "PLANS_TO": ("计划", "plans to"),
    "FEELS": ("感到", "feels"),
    "CREATES": ("创建", "creates"),
    "CONTRIBUTES_TO": ("参与贡献", "contributes to"),
    "DEVELOPS": ("开发", "develops"),
    "MAINTAINS": ("维护", "maintains"),
    "WORKS_ON": ("正在做", "works on"),
}


def render_grounded_fact(claim: L2Phase1FactClaim, *, language: str | None = None) -> str:
    """Render a supported positive predicate without adding model-authored facts."""
    if claim.polarity != "positive":
        return ""
    wording = _PREDICATE_WORDING.get(str(claim.predicate).upper())
    if wording is None:
        return ""
    zh = (language or effective_app_language_code()).startswith("zh")
    subject = "用户" if zh else "The user"
    if claim.subject_type not in {"user", "person"}:
        subject = claim.subject_ref
    value = " ".join(str(claim.object_ref).split())
    cue = str(claim.temporal_cue)
    qualifier = {"recent": "最近", "one_off": "曾在一次经历中"}.get(cue, "") if zh else {
        "recent": "recently ", "one_off": "on one occasion "
    }.get(cue, "")
    text = f"{subject}{qualifier}{wording[0]}{value}。" if zh else f"{subject} {qualifier}{wording[1]} {value}."
    if claim.raw_time_expression:
        label = "原文时间" if zh else "Time as stated"
        text += f" {label}: {claim.raw_time_expression}"
    return text


def render_behavior_observation(value: str, *, recent: bool, language: str | None = None) -> str:
    """Describe behavioral evidence as an inference, never a declared preference."""
    zh = (language or effective_app_language_code()).startswith("zh")
    if zh:
        horizon = "近期" if recent else "多次"
        return f"根据{horizon}活动推测，你可能关注「{value}」。"
    horizon = "recent" if recent else "repeated"
    return f"Your {horizon} activity suggests you may be interested in {value}."


def assertion_evidence_basis(assertion: dict) -> str:
    """Classify product provenance independently of confidence and validation rank."""
    if assertion.get("user_feedback") == "confirmed":
        return "user_confirmed"
    if assertion.get("inference_depth") in {"direct", "explicit"}:
        return "direct_report"
    if assertion.get("inference_depth"):
        return "inferred"
    return "unknown"
