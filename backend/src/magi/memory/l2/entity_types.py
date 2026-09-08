"""Ordered entity semantics shared by extraction, validation and presentation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EntityTypeDefinition:
    """One canonical category; category membership never establishes identity."""

    key: str
    description: str
    boundary: str
    label_en: str
    label_zh: str
    aliases: tuple[str, ...] = ()
    structured_only: bool = False
    examples: tuple[str, ...] = ()


# Tuple order is part of the prompt contract. Sets are only used for membership.
ENTITY_TYPES: tuple[EntityTypeDefinition, ...] = (
    EntityTypeDefinition("person", "an individual human", "Shared names do not identify the same person.", "Person", "人物"),
    EntityTypeDefinition("place", "a physical or geographic location", "A venue as a location is distinct from its operating organization.", "Place", "地点"),
    EntityTypeDefinition("organization", "a formal company or institution", "Exclude its brands, products, services and informal collectives.", "Organization", "组织", examples=("Apple Inc. employs me -> organization; I like the Apple brand -> brand.",)),
    EntityTypeDefinition("group", "a named band, team, community or collective", "Use for the collective itself, not a member or a work it creates.", "Group", "团体", examples=("A band called Apple -> group; a company called Apple -> organization. Shared spelling is not shared identity.",)),
    EntityTypeDefinition("brand", "a commercial brand identity", "Distinct from its owner and individual products; ownership needs separate evidence.", "Brand", "品牌"),
    EntityTypeDefinition("product", "a named commercial product", "Prefer hardware for physical devices and software for applications; exclude brands and services.", "Product", "产品"),
    EntityTypeDefinition("service", "a named service offering such as delivery, repair or consulting", "An application used to obtain a service is software; its provider is an organization.", "Service", "服务", examples=("A home repair service -> service; its booking app -> software.",)),
    EntityTypeDefinition("food", "a specific food, dish, drink, snack or ingredient", "An edible item is distinct from a same-named brand or company.", "Food", "食物", ("dish", "drink", "snack", "ingredient"), examples=("I like eating apples -> food; I use Apple computers -> brand/hardware according to the referent.",)),
    EntityTypeDefinition("software", "an application, digital platform, operating system or database", "Exclude the company, brand, service offering and underlying technical method.", "Software", "软件", ("app", "application", "platform", "os", "database")),
    EntityTypeDefinition("technology", "a language, framework, algorithm, model, standard or protocol", "Distinguish a method or standard from its implementation and vendor.", "Technology", "技术", ("language", "framework", "algorithm", "model")),
    EntityTypeDefinition("hardware", "a physical device or computing component", "Prefer this over product for devices; distinguish model names from uniquely identified individual devices.", "Hardware", "硬件", ("device", "console", "phone")),
    EntityTypeDefinition("virtual_object", "a specific digital asset, account, document or virtual item", "A document instance is distinct from its file format and application.", "Digital object", "数字对象"),
    EntityTypeDefinition("project", "a named, reusable body of work", "Not a one-time action sentence or a complete plan.", "Project", "项目"),
    EntityTypeDefinition("activity", "a reusable practice or activity", "not a complete plan or action clause; a particular occurrence is an event.", "Activity", "活动"),
    EntityTypeDefinition("event", "a named or clearly bounded occurrence", "Distinct occurrences remain separate even when their titles match.", "Event", "事件"),
    EntityTypeDefinition("animal", "an animal species or non-personal animal", "Use pet for a specific companion animal.", "Animal", "动物"),
    EntityTypeDefinition("pet", "a specific companion animal", "Its species is an attribute or separate referent, not its identity.", "Pet", "宠物"),
    EntityTypeDefinition("health_metric", "a named measurable health quantity", "Exclude a diagnosis, medication or ungrounded health inference.", "Health metric", "健康指标"),
    EntityTypeDefinition("concept", "an abstract idea, quality, style or preference", "A quality is distinct from a subject area and a complete proposition.", "Concept", "概念", ("idea", "principle", "theory"), examples=("Minimalism as an aesthetic -> concept; studying architecture -> topic.",)),
    EntityTypeDefinition("skill", "a learnable, reusable capability", "A capability is distinct from one occasion of performing it.", "Skill", "技能"),
    EntityTypeDefinition("media", "a named song, album, film, book, podcast or creative work", "Distinct from its creator, genre and a particular local file.", "Creative work", "作品"),
    EntityTypeDefinition("topic", "a reusable subject area", "Not a sentence about the subject, a quality or a particular work.", "Topic", "主题"),
    EntityTypeDefinition("other", "a concrete reusable entity that fits no more specific type", "Not a substitute for uncertain identity, unknown type, missing evidence or an unfamiliar name.", "Other", "其他"),
    EntityTypeDefinition("weather_state", "a structured weather condition", "Source-owned state identity.", "Weather state", "天气状态", structured_only=True),
    EntityTypeDefinition("location_state", "a structured location or movement state", "Source-owned state identity.", "Location state", "位置状态", structured_only=True),
    EntityTypeDefinition("time_point", "a structured temporal point or anchor", "Source-owned temporal identity.", "Time point", "时间点", structured_only=True),
    EntityTypeDefinition("session_topic", "the bounded subject of a conversation session", "Source-owned session identity.", "Session topic", "会话主题", structured_only=True),
    EntityTypeDefinition("presence", "a structured presence or availability state", "Source-owned presence identity.", "Presence", "在场状态", structured_only=True),
)

ENTITY_TYPE_REGISTRY = frozenset(item.key for item in ENTITY_TYPES)
ENTITY_TYPE_ALIASES = {alias: item.key for item in ENTITY_TYPES for alias in item.aliases}
EXTRACTABLE_ENTITY_TYPES = frozenset(item.key for item in ENTITY_TYPES if not item.structured_only)


def render_entity_type_instructions() -> str:
    """Render deterministic instructions without request or user-specific data."""
    lines = ["## Allowed Entity Types"]
    for item in ENTITY_TYPES:
        if item.structured_only:
            continue
        lines.append(f"- `{item.key}` — {item.description}. {item.boundary}")
        if item.aliases:
            lines.append(f"  Type aliases: {', '.join(item.aliases)} -> {item.key}.")
        for example in item.examples:
            lines.append(f"  Boundary example (not evidence): {example}")
    lines.extend([
        "", "### Structured source types",
        "Only reuse existing source-owned entities of these types; do not invent them from chat:",
    ])
    for item in ENTITY_TYPES:
        if item.structured_only:
            lines.append(f"- `{item.key}` — {item.description}.")
    return "\n".join(lines)
