# Entity-Facet Modeling Plan

## Background

The current L2 memory modeling has reached a point where plain triples and flat assertions are no longer enough for conversational continuity. Two recurring issues have become clear:

1. The system needs to distinguish between concrete, referable instances and generic concepts.
2. Some high-value entities require structured slots, but introducing a brand-new top-level entity type for every new noun would cause unbounded ontology growth.

Examples:

- Interview conversations:
  - `明天要去面试好烦`
  - `哪家公司？`
  - `阿里`
- Pet conversations:
  - `听说小王养了只狗`
  - `啥颜色的呀`
  - `黑的，取名叫丫丫`

In both cases, the system must preserve:

- stable graph connectivity between entities
- enough structure to support slot completion in later turns
- a bounded ontology that does not require one new top-level type per domain noun

This document proposes a modeling split between:

- coarse-grained entity types
- graph relations
- optional facet / slot-pack schemas

## Design Goals

1. Keep top-level entity types finite and stable.
2. Support referable concrete instances such as one interview, one pet, one trip.
3. Support generic concept-level entities such as `dog`, `interview`, `rainy weather`.
4. Avoid promoting every recurring noun into a first-class entity type.
5. Preserve graph query power for high-value cross-entity relations.
6. Support structured slot updates for a small set of high-value conversational objects.
7. Allow long-tail domains to remain representable without schema explosion.

## Core Principle

Do not create a new top-level entity type for each noun.

Instead, model memory using three layers:

1. Coarse-grained entity types
2. Relations between entities
3. Optional facet / slot-pack schemas attached to some entities

In short:

- `type` answers: what broad kind of thing is this?
- `relation` answers: how is this thing connected to another thing?
- `facet` answers: what structured fields are worth tracking for this thing?

## Layer 1: Coarse-Grained Entity Types

Top-level entity types should remain small, stable, and reusable across domains.

Recommended canonical set:

- `person`
- `organization`
- `place`
- `group`
- `event`
- `activity`
- `project`
- `product`
- `software`
- `technology`
- `media`
- `concept`
- `skill`
- `food`
- `animal`
- `pet`
- `other`

Notes:

- `interview` is not a top-level entity type. It should be modeled as `event`.
- A specific dog owned by someone is not `concept:dog`; it is a `pet` instance.
- `dog` as a generic animal category remains a concept/species node, not a pet instance.
- Additional domain nouns should not become top-level types unless they are broadly reusable and clearly distinct at the ontology level.

## Layer 2: Relations

Relations are for connections between two independent objects.

Use graph relations when:

- both sides can be referred to independently later
- the connection itself is meaningful for retrieval or reasoning
- the object is not just a literal slot value

Examples:

- `user:self PLANS_TO event:interview_x`
- `event:interview_x INTERVIEW_WITH organization:alibaba-group`
- `person:xiaowang OWNS pet:pet_001`
- `pet:pet_001 INSTANCE_OF concept:dog`

Recommended rule of thumb:

- if the value should remain queryable as a node later, use a relation
- if the value is just a scalar field on the entity, use a facet slot

## Layer 3: Facets / Slot Packs

Facets are domain-specific structured slot bundles attached to entities of an existing coarse type.

A facet is not a new top-level type.

Examples:

- `event` entity + `interview_event` facet
- `pet` entity + `owned_pet` facet

A facet should exist only when:

1. the domain appears frequently enough
2. users often provide follow-up slot completions
3. retrieval or reasoning benefits from structured fields
4. plain graph edges and free-form assertions are no longer sufficient

A facet should not exist merely because a noun appeared once.

## When to Add a New Facet

A domain should be promoted to a facet only if all or most of the following hold:

- It appears repeatedly in user conversations.
- Later turns often fill in missing details.
- The details are predictable enough to fit a stable slot set.
- The filled slots are useful for future retrieval, planning, or memory grounding.

Good facet candidates:

- interview events
- owned pets
- recurring projects

Poor early facet candidates:

- one-off movie mentions
- casual, low-value object mentions
- ad hoc concepts with no later slot completion behavior

## Long-Tail Strategy

Long-tail domains should not block ingestion.

When no facet exists yet:

- create the entity using a coarse type
- store graph relations where appropriate
- keep extra structured details in `extra_attributes_json` or equivalent extension storage
- only promote to a facet later if the pattern becomes frequent and valuable

This gives the system a controlled path:

1. store now
2. observe recurrence
3. formalize later

## Instance vs Generic Concept

This is a core distinction.

### Concrete Instance

A concrete instance is a specific thing being discussed or updated.

Examples:

- one interview tomorrow
- Xiao Wang's specific dog
- one trip to Hangzhou

Concrete instances can:

- accumulate structured slots
- be referred to in later turns
- anchor follow-up slot completion
- connect to multiple other entities

### Generic Concept

A generic concept refers to a class, category, or broad preference target.

Examples:

- dogs in general
- interviews in general
- rainy weather in general

Generic concepts should not receive instance-specific slot updates such as:

- name
- exact color
- interview round number
- exact scheduled time

### Practical Heuristic

Treat something as a concrete instance when any of the following apply:

- it is introduced as one specific object: `一个`, `一只`, `这只`, `那次`, `这个`
- it is anchored by ownership, time, place, or planned participation
- later turns ask for slot details about it
- it can be resumed with a pronoun or follow-up completion

Treat something as a generic concept when:

- it describes a broad preference or category
- there is no concrete anchor event or owner
- the utterance is category-level rather than instance-level

## Example A: Interview Modeling

Conversation:

- `明天要去面试好烦`
- `哪家公司？`
- `阿里`

Recommended model:

Entities:

- `user:self` with type `user`
- `event:interview_x` with coarse type `event`
- `organization:alibaba-group` with coarse type `organization`

Relations:

- `user:self PLANS_TO event:interview_x`
- `event:interview_x INTERVIEW_WITH organization:alibaba-group`

Facet:

- `interview_event` attached to `event:interview_x`

Suggested `interview_event` slots:

- `scheduled_at`
- `role_title`
- `round_index`
- `stage`
- `status`
- `mode`
- `location_text`
- `notes`

Optional derived convenience edge:

- `user:self INTERVIEWS_AT organization:alibaba-group`

This edge is useful for retrieval convenience, but it should be treated as derived from the event-centered structure rather than replacing it.

### Interview Slot Boundary

Use relations for:

- `organization_id`
- `place_id`
- optional `time_point` if the system wants reusable time nodes

Use slots for:

- `round_index`
- `stage`
- `status`
- `mode`
- `role_title`
- `location_text`
- `notes`

In general:

- reusable object -> relation
- scalar event field -> slot

## Example B: Pet Modeling

Conversation:

- `听说小王养了只狗`
- `啥颜色的呀`
- `黑的，取名叫丫丫`

Recommended model:

Entities:

- `person:xiaowang`
- `pet:pet_001`
- `concept:dog`

Relations:

- `person:xiaowang OWNS pet:pet_001`
- `pet:pet_001 INSTANCE_OF concept:dog`

Facet:

- `owned_pet` attached to `pet:pet_001`

Suggested `owned_pet` slots:

- `name`
- `color`
- `breed`
- `sex`
- `age_text`
- `medical_notes`

Then for the follow-up:

- `黑的` updates `owned_pet.color = black`
- `取名叫丫丫` updates `owned_pet.name = 丫丫`

If a later utterance says:

- `他很喜欢狗啊`

that should target the generic concept node:

- `person:xiaowang LIKES concept:dog`

not the specific pet instance.

## Proposed Data Model

This proposal does not require a full database redesign immediately, but the conceptual model should be treated as:

### Entity

- `entity_id`
- `entity_type`
- `canonical_name`
- `facet_names[]`
- `extra_attributes_json`

### Relation

- `subject_id`
- `predicate`
- `object_id`
- evidence fields
- conflict status

### Facet Instance

- `entity_id`
- `facet_name`
- `slots_json`
- `updated_at`
- evidence fields

This can be implemented either as:

1. dedicated facet tables per high-value facet, or
2. one generic `entity_facets` table with typed JSON payloads

The implementation choice can remain open for now. The architectural requirement is the split between coarse entity type and facet schema.

## Proposed Facet Registry

The system should maintain a bounded registry of facet definitions.

Each facet definition should specify:

- `facet_name`
- allowed host entity types
- supported slots
- slot value kinds
- slot validation rules
- whether the slot points to another entity or is scalar-only

Example shape:

```json
{
  "facet_name": "interview_event",
  "host_entity_types": ["event"],
  "slots": {
    "organization_id": {"kind": "entity_ref", "target_types": ["organization"]},
    "scheduled_at": {"kind": "datetime"},
    "role_title": {"kind": "text"},
    "round_index": {"kind": "integer"},
    "stage": {"kind": "enum"},
    "status": {"kind": "enum"},
    "mode": {"kind": "enum"},
    "location_text": {"kind": "text"}
  }
}
```

Another example:

```json
{
  "facet_name": "owned_pet",
  "host_entity_types": ["pet"],
  "slots": {
    "name": {"kind": "text"},
    "color": {"kind": "enum_or_text"},
    "breed": {"kind": "text"},
    "sex": {"kind": "enum"},
    "age_text": {"kind": "text"}
  }
}
```

## LLM and Schema Boundary

Facet slot names should not be model-invented.

Recommended contract:

- the system defines canonical slot names
- the LLM extracts slot-value candidates
- program logic validates and normalizes them

Good pattern:

- fixed schema names
- model-generated values
- deterministic normalization and acceptance rules

Bad pattern:

- letting the model invent arbitrary slot keys such as `company_name`, `target_org`, `interview_target`, `pet_nickname`, `animal_color_desc`

The latter leads to schema drift and retrieval instability.

## Relation vs Slot Decision Rule

For any candidate detail, ask:

Is this detail another object that may be queried, referenced, or linked later?

- if yes, prefer relation
- if no, prefer slot

Examples:

- company -> relation
- place -> usually relation
- time point -> relation only if reusable time nodes are desired; otherwise slot
- round number -> slot
- stage -> slot
- pet name -> slot
- pet species -> relation to concept/species node

## Proposed Additions to L2 Ontology

This modeling approach implies a few additions:

### New or clarified graph predicates

Recommended:

- `INTERVIEW_WITH`
- `INSTANCE_OF`

Optional derived convenience predicate:

- `INTERVIEWS_AT`

### Facet-aware entity updates

L2 should support:

- create instance entity
- attach facet if host type allows it
- update slots from later conversational turns
- keep graph relations and facet slots synchronized where necessary

## Conversational Slot Completion Implication

This design directly supports slot completion.

Example:

- user creates `event:interview_x`
- assistant asks `哪家公司？`
- user replies `阿里`

The reply should not be treated as an isolated organization mention only.

Instead, the system should:

1. detect an open conversational slot anchored to `event:interview_x`
2. validate that the reply resolves to an `organization`
3. update the event structure via:
   - relation `event:interview_x INTERVIEW_WITH organization:alibaba-group`
   - optional slot mirror if the facet stores `organization_id`

This is precisely why a facet plus relation hybrid is preferable to a flat attribute-only model.

## Migration Guidance

This document does not require immediate migration of all L2 entities.

Recommended phased adoption:

### Phase 1

- keep existing coarse entity types
- add facet registry abstraction
- add `INTERVIEW_WITH` and `INSTANCE_OF`
- add slot completion support for one facet: `interview_event`

### Phase 2

- add `owned_pet` facet
- support instance-vs-generic disambiguation in more contexts
- begin storing facet payloads in a dedicated persistence layer

### Phase 3

- introduce convenience derived edges where useful for retrieval
- expand retrieval to expose facet slots directly
- add slot-aware query-time retrieval logic

## Out of Scope

This document does not define:

- the final storage table layout for facet persistence
- the full list of future facets
- generalized multi-hop facet reasoning
- UI/editor support for facet inspection

Those should follow in implementation-specific plans.

## Recommendations

1. Keep entity types coarse and bounded.
2. Add new top-level types sparingly.
3. Use relations for cross-entity connectivity.
4. Use facets for high-value structured slot packs.
5. Treat instance-vs-generic disambiguation as a first-class modeling rule.
6. Do not let the LLM invent facet field names.
7. Promote long-tail domains gradually, based on recurrence and value.

## Summary

The correct scaling strategy is not:

- one noun -> one new entity type

It is:

- few coarse entity types
- reusable graph relations
- optional facet schemas for high-value patterns

Under this model:

- interviews remain `event` entities with an `interview_event` facet
- owned dogs remain `pet` entities with an `owned_pet` facet
- broad categories like `dog` remain concept-level nodes

This preserves ontology stability while still enabling structured memory growth.
