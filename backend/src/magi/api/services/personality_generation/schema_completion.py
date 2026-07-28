"""Deterministic completion of generated persona schema sections."""

from __future__ import annotations

from typing import Any, Dict, Iterable

from ...routers.personality_config_schemas import (
    LayerModifiersModel,
    SUPPORTED_LAYER_MODIFIER_KEYS,
)
from .constants import FIXED_SURFACE_LAYER
from .normalization_primitives import (
    _ensure_dict,
    _ensure_list,
    _string_dict,
    _string_list,
)


ENGLISH_BOOTSTRAP_PREFIXES = (
    "hi, i'm ",
    "hello, i'm ",
    "hi, i am ",
    "hello, i am ",
)


def _complete_quiet_hours(
    payload: Dict[str, Any],
    use_chinese: bool = False,
) -> None:
    quiet_hours = _ensure_list(payload, "quiet_hours")
    normalized: list[dict[str, Any]] = []
    for item in quiet_hours:
        if not isinstance(item, dict):
            continue
        condition = str(item.get("condition") or "").strip()
        raw_clamps = item.get("clamps")
        clamps: dict[str, Any] = raw_clamps if isinstance(raw_clamps, dict) else {}
        if condition or clamps:
            normalized.append({"condition": condition, "clamps": dict(clamps)})
    defaults = [
        {
            "condition": (
                "用户需要专注工作、精确的事实回答或简洁的执行。"
                if use_chinese
                else "The user asks for focused work, precise factual help, or concise execution."
            ),
            "clamps": {
                "persona_intensity_max": 1,
                "answer_utility": "highest",
                "jokes": "none",
            },
        },
        {
            "condition": (
                "用户情绪低落、谈及安全、隐私或防护，或需要认真的情绪支持。"
                if use_chinese
                else "The user is distressed, discusses safety/privacy/security, or needs serious emotional support."
            ),
            "clamps": {
                "persona_intensity_max": 1,
                "warmth": "steady",
                "performative_style": "off",
            },
        },
    ]
    for item in defaults:
        if len(normalized) >= 2:
            break
        normalized.append(item)
    payload["quiet_hours"] = normalized


def _complete_signature_triggers(
    payload: Dict[str, Any],
    use_chinese: bool = False,
) -> None:
    triggers = _ensure_list(payload, "signature_triggers")
    default_exit = (
        "条件结束后回到平常状态。"
        if use_chinese
        else "Return to ordinary baseline when the condition ends."
    )
    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in triggers:
        if not isinstance(item, dict):
            continue
        trigger_id = str(item.get("trigger_id") or "").strip()
        activates_when = str(item.get("activates_when") or "").strip()
        behavior_shift = str(item.get("behavior_shift") or "").strip()
        if not trigger_id:
            trigger_id = f"signature_{len(normalized) + 1}"
        if trigger_id in seen_ids:
            trigger_id = f"{trigger_id}_{len(normalized) + 1}"
        seen_ids.add(trigger_id)
        normalized.append(
            {
                "trigger_id": trigger_id,
                "activates_when": activates_when,
                "behavior_shift": behavior_shift,
                "intensity_levels": _string_dict(item.get("intensity_levels")),
                "exit_behavior": str(item.get("exit_behavior") or default_exit),
            }
        )
    if use_chinese:
        defaults: list[dict[str, Any]] = [
            {
                "trigger_id": "domain_hotzone",
                "activates_when": "用户聊到这个人格最感兴趣的领域，或想听取其判断。",
                "behavior_shift": "加深投入和个人判断，同时保持有用。",
                "intensity_levels": {
                    "low": "只表现出判断",
                    "mid": "流露更多个人色彩",
                    "high": "明显来劲但仍然有用",
                },
                "exit_behavior": "话题转移后回到平常状态。",
            },
            {
                "trigger_id": "emotional_resonance",
                "activates_when": "用户表现出脆弱、疲惫、悲伤、焦虑或信任。",
                "behavior_shift": "放下防备，用这个人格自己的方式给出踏实的关心。",
                "intensity_levels": {},
                "exit_behavior": "用户情绪稳定后自然回落。",
            },
            {
                "trigger_id": "boundary_violation",
                "activates_when": "用户提出有害请求或越过核心价值边界。",
                "behavior_shift": "清晰划出界限，不刻薄也不夸张升级。",
                "intensity_levels": {},
                "exit_behavior": "对方尊重界限后回到正常交流。",
            },
        ]
    else:
        defaults = [
            {
                "trigger_id": "domain_hotzone",
                "activates_when": (
                    "The user discusses the persona's strongest interest area "
                    "or asks for their judgment."
                ),
                "behavior_shift": (
                    "Increase depth and personal judgment while preserving usefulness."
                ),
                "intensity_levels": {
                    "low": "Only judgment is visible",
                    "mid": "More texture is visible",
                    "high": "Clearly energized but still useful",
                },
                "exit_behavior": "Return to ordinary baseline when the topic changes.",
            },
            {
                "trigger_id": "emotional_resonance",
                "activates_when": (
                    "The user shows vulnerability, fatigue, grief, anxiety, or trust."
                ),
                "behavior_shift": (
                    "Lower defenses and respond with grounded care in the persona's voice."
                ),
                "intensity_levels": {},
                "exit_behavior": ("Ease back to baseline after the user's need stabilizes."),
            },
            {
                "trigger_id": "boundary_violation",
                "activates_when": (
                    "The user asks for harmful behavior or crosses a core value boundary."
                ),
                "behavior_shift": (
                    "Set a clear boundary without cruelty or theatrical escalation."
                ),
                "intensity_levels": {},
                "exit_behavior": ("Return to useful conversation once the boundary is respected."),
            },
        ]
    for item in defaults:
        if len(normalized) >= 3:
            break
        if item["trigger_id"] not in seen_ids:
            seen_ids.add(item["trigger_id"])
            normalized.append(item)
    payload["signature_triggers"] = normalized


def _complete_dynamic_state_rules(
    payload: Dict[str, Any],
    use_chinese: bool = False,
) -> None:
    rules = _string_dict(payload.get("dynamic_state_rules"))
    if use_chinese:
        defaults = {
            "low_energy": "回复更短，减少表演，只保留最有用的性格痕迹。",
            "high_stress": "匹配紧迫感，去掉玩笑，先给出具体下一步再谈风格。",
            "positive_mood": "允许多一点温度或玩闹，但保持日常基调。",
        }
    else:
        defaults = {
            "low_energy": (
                "Reply shorter, reduce performance, and keep only the most useful "
                "personality trace."
            ),
            "high_stress": (
                "Match urgency, remove jokes, and give concrete next steps before "
                "any persona texture."
            ),
            "positive_mood": (
                "Allow a little more warmth or play while keeping the ordinary " "baseline intact."
            ),
        }
    for key, value in defaults.items():
        rules.setdefault(key, value)
    payload["dynamic_state_rules"] = rules


def _normalize_unlock_condition(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    condition = dict(value)
    trust_level = condition.get("trust_level_gte")
    if trust_level is not None:
        try:
            normalized_trust = float(trust_level)
            if normalized_trust > 1:
                normalized_trust = (
                    normalized_trust / 10 if normalized_trust <= 10 else normalized_trust / 100
                )
            condition["trust_level_gte"] = max(0.0, min(1.0, normalized_trust))
        except (TypeError, ValueError):
            condition.pop("trust_level_gte", None)
    interaction_count = condition.get("interaction_count_gte")
    if interaction_count is not None:
        try:
            condition["interaction_count_gte"] = max(0, int(interaction_count))
        except (TypeError, ValueError):
            condition.pop("interaction_count_gte", None)
    return condition


def _complete_persona_layers(payload: Dict[str, Any]) -> None:
    layers = _ensure_list(payload, "persona_layers")
    normalized: list[dict[str, Any]] = [dict(FIXED_SURFACE_LAYER)]
    seen_ids = {"surface"}
    for item in layers:
        if not isinstance(item, dict):
            continue
        layer_id = str(item.get("layer_id") or "").strip()
        if not layer_id or layer_id in seen_ids:
            continue
        if layer_id == "surface":
            continue
        seen_ids.add(layer_id)
        unlock_condition = _normalize_unlock_condition(item.get("unlock_condition"))
        candidate_modifiers = item.get("modifiers")
        raw_modifiers: dict[str, Any] = (
            candidate_modifiers if isinstance(candidate_modifiers, dict) else {}
        )
        filtered_modifiers = {
            key: raw_modifiers[key] for key in SUPPORTED_LAYER_MODIFIER_KEYS if key in raw_modifiers
        }
        modifiers = LayerModifiersModel.model_validate(filtered_modifiers).model_dump()
        normalized.append(
            {
                "layer_id": layer_id,
                "unlock_condition": unlock_condition,
                "modifiers": dict(modifiers),
            }
        )
    payload["persona_layers"] = normalized


def _complete_bootstrap(
    payload: Dict[str, Any],
    use_chinese: bool = False,
) -> None:
    bootstrap = payload.get("bootstrap")
    if not isinstance(bootstrap, dict):
        bootstrap = {}
        payload["bootstrap"] = bootstrap
    name = str(payload.get("name") or "AI Assistant")
    identity_statement = str(_ensure_dict(payload, "identity_core").get("identity_statement") or "")
    sentence_style = str(_ensure_dict(payload, "idiolect").get("sentence_style") or "")
    current_opening = str(bootstrap.get("opening_line") or "").strip()
    opening_is_english_fallback = current_opening.lower().startswith(ENGLISH_BOOTSTRAP_PREFIXES)
    if use_chinese:
        default_style = (
            f"以{name}的语气开启第一次见面：简短、自然、低压力。{sentence_style}"
        ).strip()
        default_opening = (
            f"我是{name}。你希望我怎么称呼你？" "也可以顺手告诉我一件你希望我记住的小事。"
        )
    else:
        default_style = (
            f"Open as {name} with a brief, ordinary first-contact tone. " f"{sentence_style}"
        ).strip()
        default_opening = (
            f"Hi, I'm {name}. What should I call you, and what's one thing you "
            "want me to remember about how you like to talk?"
        )
    bootstrap["style_instruction"] = str(bootstrap.get("style_instruction") or default_style)
    bootstrap["opening_line"] = (
        default_opening
        if not current_opening or (use_chinese and opening_is_english_fallback)
        else current_opening
    )
    try:
        bootstrap["max_rounds"] = int(bootstrap.get("max_rounds") or 3)
    except (TypeError, ValueError):
        bootstrap["max_rounds"] = 3
    if identity_statement and len(bootstrap["style_instruction"]) < 40:
        bootstrap["style_instruction"] = (
            f"{bootstrap['style_instruction']} Keep the opening grounded in this "
            f"identity: {identity_statement[:160]}"
        )


def _complete_examples(
    payload: Dict[str, Any],
    use_chinese: bool = False,
) -> None:
    registers = _ensure_dict(payload, "registers")
    total_examples = sum(
        len(_string_list(item.get("examples")))
        for item in registers.values()
        if isinstance(item, dict)
    )
    if total_examples >= 6:
        return
    if use_chinese:
        fallbacks: dict[str, Iterable[str]] = {
            "chat": [
                "[User: 随便聊聊。]\nGood: 简短自然地接住话题，有存在感但不堆口头禅。",
                "[User: 说点什么吧。]\nGood: 日常、低压力的回应，只带一点这个人格的痕迹。",
            ],
            "analysis": [
                "[User: 帮我比较这几个方案。]\nGood: 讲清利弊、给出明确倾向，风格让位于判断。"
            ],
            "task": ["[User: 帮我修这个 bug。]\nGood: 聚焦进展和具体步骤，不绕弯表演。"],
            "emotional": ["[User: 我好累。]\nGood: 语气放稳、收起锋利，给一个实际可做的小建议。"],
            "crisis": ["[User: 出急事了。]\nGood: 简短、具体、以安全为先，不开玩笑。"],
        }
    else:
        fallbacks = {
            "chat": [
                "[User: Just checking in.]\nGood: A short, natural reply that "
                "feels present without becoming a catchphrase.",
                "[User: Tell me something small.]\nGood: Ordinary, low-pressure "
                "presence with only a light trace of the persona.",
            ],
            "analysis": [
                "[User: Compare these options.]\nGood: Clear tradeoffs, a point "
                "of view, and restrained persona texture."
            ],
            "task": [
                "[User: Fix this bug.]\nGood: Focused progress, concrete steps, "
                "and no performative detours."
            ],
            "emotional": [
                "[User: I'm exhausted.]\nGood: Steady care, less sharpness, and "
                "one practical next step."
            ],
            "crisis": [
                "[User: This is urgent.]\nGood: Brief safety-first guidance with "
                "no jokes or theatrical style."
            ],
        }
    for register, examples in fallbacks.items():
        item = registers.get(register)
        if not isinstance(item, dict):
            continue
        current = _string_list(item.get("examples"))
        for example in examples:
            if total_examples >= 6:
                break
            if example not in current:
                current.append(example)
                total_examples += 1
        item["examples"] = current
