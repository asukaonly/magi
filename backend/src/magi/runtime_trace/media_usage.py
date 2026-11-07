"""Normalize image and speech usage counters without retaining media or text."""

from typing import Any


def openai_media_usage(raw: dict[str, Any] | None, *, output_modality: str) -> dict[str, int] | None:
    if not raw:
        return None
    try:
        incoming = raw['input_token_details'] if 'input_token_details' in raw else raw['input_tokens_details']
        outgoing = raw.get('output_token_details') or raw.get('output_tokens_details')
        result = {'input_tokens': int(raw['input_tokens']), 'output_tokens': int(raw['output_tokens'])}
        cached = incoming.get('cached_tokens_details') or {}
        for modality in ('text', 'image', 'audio'):
            result[f'{modality}_input_tokens'] = int(incoming.get(f'{modality}_tokens', 0))
            result[f'cached_{modality}_input_tokens'] = int(cached.get(f'{modality}_tokens', 0))
            result[f'{modality}_output_tokens'] = int(outgoing.get(f'{modality}_tokens', 0)) if outgoing else (
                result['output_tokens'] if modality == output_modality else 0)
        if int(incoming.get('cached_tokens', 0)) != sum(result[f'cached_{m}_input_tokens'] for m in ('text', 'image', 'audio')):
            return None
        return result
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        return None


def gemini_image_usage(raw: dict[str, Any] | None) -> dict[str, int] | None:
    if not raw:
        return None
    try:
        thoughts = int(raw.get('total_thought_tokens', 0))
        result = {'input_tokens': int(raw['total_input_tokens']),
                  'output_tokens': int(raw['total_output_tokens']) + thoughts}
        for direction, field in [('input', 'input_tokens_by_modality'), ('output', 'output_tokens_by_modality'),
                                 ('cached_input', 'cached_tokens_by_modality')]:
            for item in raw.get(field, []):
                modality = item['modality']
                if modality not in ('text', 'image', 'audio'):
                    return None
                key = f'cached_{modality}_input_tokens' if direction == 'cached_input' else f'{modality}_{direction}_tokens'
                result[key] = result.get(key, 0) + int(item['tokens'])
        result['text_output_tokens'] = result.get('text_output_tokens', 0) + thoughts
        if int(raw.get('total_cached_tokens', 0)) != sum(result.get(f'cached_{m}_input_tokens', 0) for m in ('text', 'image', 'audio')):
            return None
        if raw.get('total_tool_use_tokens'):
            return None
        return result
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        return None
