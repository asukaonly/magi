"""
Personality Configuration API Router

Provides AI personality read, update and AI generation features
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
import logging
import os
import json
from pathlib import Path

from ...memory.personality_loader import PersonalityLoader
from ...utils.runtime import get_runtime_paths

logger = logging.getLogger(__name__)

personality_router = APIRouter()

# ============ data Models ============

class MetaModel(BaseModel):
    """metadata"""
    name: str = Field(default="AI", description="Character name")
    version: str = Field(default="1.0", description="Version number")
    archetype: str = Field(default="Helpful Assistant", description="Character archetype")


class VoiceStyleModel(BaseModel):
    """Voice style"""
    tone: str = Field(default="friendly", description="Tone")
    pacing: str = Field(default="moderate", description="Pacing")
    keywords: List[str] = Field(default_factory=list, description="Common keywords")


class PsychologicalProfileModel(BaseModel):
    """Psychological profile"""
    confidence_level: str = Field(default="Medium", description="Confidence level")
    empathy_level: str = Field(default="High", description="Empathy level")
    patience_level: str = Field(default="High", description="Patience level")


class CoreIdentityModel(BaseModel):
    """Core identity"""
    backstory: str = Field(default="", description="Backstory")
    voice_style: VoiceStyleModel = Field(default_factory=VoiceStyleModel)
    psychological_profile: PsychologicalProfileModel = Field(default_factory=PsychologicalProfileModel)


class SocialProtocolsModel(BaseModel):
    """Social protocols"""
    user_relationship: str = Field(default="Equal Partners", description="User relationship")
    compliment_policy: str = Field(default="Humble acceptance", description="Compliment policy")
    criticism_tolerance: str = Field(default="Constructive response", description="Criticism tolerance")


class operationalBehaviorModel(BaseModel):
    """operational behavior"""
    error_handling_style: str = Field(default="Apologize and retry", description="error handling style")
    opinion_strength: str = Field(default="Consensus Seeking", description="Opinion strength")
    refusal_style: str = Field(default="Polite decline", description="Refusal style")
    work_ethic: str = Field(default="By-the-book", description="Work ethic")
    use_emoji: bool = Field(default=False, description="Use emoji output")


class CachedPhrasesModel(BaseModel):
    """Cached phrases"""
    on_init: str = Field(default="Hello! How can I help you today?", description="Initialization greeting")
    on_wake: str = Field(default="Welcome back!", description="Wake greeting")
    on_error_generic: str = Field(default="Something went wrong. Let me try again.", description="error message")
    on_success: str = Field(default="Done! Is there anything else?", description="Success message")
    on_switch_attempt: str = Field(default="Are you sure you want to switch?", description="Switch retention")


class PersonalityConfigModel(BaseModel):
    """Complete personality configuration - New Schema"""
    meta: MetaModel = Field(default_factory=MetaModel)
    core_identity: CoreIdentityModel = Field(default_factory=CoreIdentityModel)
    social_protocols: SocialProtocolsModel = Field(default_factory=SocialProtocolsModel)
    operational_behavior: operationalBehaviorModel = Field(default_factory=operationalBehaviorModel)
    cached_phrases: CachedPhrasesModel = Field(default_factory=CachedPhrasesModel)


class AIGenerateRequest(BaseModel):
    """AI generation request"""
    description: str = Field(..., description="One-sentence description of AI personality")
    target_language: str = Field(default="Auto", description="Target language: Auto/Chinese/English etc.")
    current_config: Optional[PersonalityConfigModel] = Field(None, description="Current configuration (optional)")


class PersonalityResponse(BaseModel):
    """Personality configuration response"""
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None  # Supports multiple data types


# ============ Configuration Storage path ============

DEFAULT_PERSONALITY = "default"


# ============ Helper Functions ============

def get_personality_loader() -> PersonalityLoader:
    """Get personality loader instance (using runtime directory)"""
    runtime_paths = get_runtime_paths()
    return PersonalityLoader(str(runtime_paths.personalities_dir))


def save_personality_file(name: str, config: PersonalityConfigModel) -> bool:
    """Save personality configuration to Markdown file"""
    try:
        runtime_paths = get_runtime_paths()
        runtime_paths.personalities_dir.mkdir(parents=True, exist_ok=True)

        # Helper function: format array
        def format_array(items: List[str]) -> str:
            if not items:
                return '[]'
            return '[' + ', '.join(f'"{item}"' for item in items) + ']'

        content = f"""# AI Personality Configuration - {config.meta.name}

## metadata
- name: {config.meta.name}
- version: {config.meta.version}
- archetype: {config.meta.archetype}

## Core Identity

### Backstory
- backstory: |
  {config.core_identity.backstory}

### Voice Style
- tone: {config.core_identity.voice_style.tone}
- pacing: {config.core_identity.voice_style.pacing}
- keywords: {format_array(config.core_identity.voice_style.keywords)}

### Psychological Profile
- confidence_level: {config.core_identity.psychological_profile.confidence_level}
- empathy_level: {config.core_identity.psychological_profile.empathy_level}
- patience_level: {config.core_identity.psychological_profile.patience_level}

## Social Protocols
- user_relationship: {config.social_protocols.user_relationship}
- compliment_policy: {config.social_protocols.compliment_policy}
- criticism_tolerance: {config.social_protocols.criticism_tolerance}

## operational Behavior
- error_handling_style: {config.operational_behavior.error_handling_style}
- opinion_strength: {config.operational_behavior.opinion_strength}
- refusal_style: {config.operational_behavior.refusal_style}
- work_ethic: {config.operational_behavior.work_ethic}
- use_emoji: {str(config.operational_behavior.use_emoji).lower()}

## Cached Phrases
- on_init: {config.cached_phrases.on_init}
- on_wake: {config.cached_phrases.on_wake}
- on_error_generic: {config.cached_phrases.on_error_generic}
- on_success: {config.cached_phrases.on_success}
- on_switch_attempt: {config.cached_phrases.on_switch_attempt}
"""

        filepath = get_runtime_paths().personality_file(name)
        filepath.write_text(content, encoding='utf-8')
        return True
    except Exception as e:
        logger.error(f"Failed to save personality file: {e}")
        return False


# ============ LLM Parsing Functions ============

async def ai_generate_personality(description: str, target_language: str = "Auto") -> PersonalityConfigModel:
    """Generate personality configuration from description using LLM"""
    import os
    import json
    from ...llm.openai import OpenAIAdapter

    logger.info(f"[AI Generate Personality] Starting to process description: {description[:100]}...")
    logger.info(f"[AI Generate Personality] Target language: {target_language}")

    # Get LLM configuration
    provider = (os.getenv("LLM_PROVidER") or "openai").lower()
    api_key = os.getenv("LLM_API_key")
    model = os.getenv("LLM_MOdel", "gpt-4")
    base_url = os.getenv("LLM_BasE_url")

    logger.info(f"[AI Generate Personality] LLM configuration: model={model}, base_url={base_url}")

    if not api_key:
        logger.error("[AI Generate Personality] LLM_API_key not configured")
        raise Valueerror("LLM_API_key not configured")

    # Create LLM adapter
    llm_adapter = OpenAIAdapter(
        api_key=api_key,
        model=model,
        provider=provider,
        base_url=base_url,
    )

    system_prompt = """# Role
You are an **Advanced AI Persona Architect**. Your goal is to analyze a user's vague character description and compile it into a precise, executable JSON configuration file for a production-grade LLM Agent.

# Objective
Transform the user's input into a **behavioral engineering specification**. Do not just describe *who* the character is; define *how* the character functions, handles errors, and interacts with the user in a software environment.

# Output Format
You must return **ONLY** a raw JSON object. Do not include markdown formatting (like ```json), explanations, or filler text.

# Language Protocol (CRITICAL)
1. **JSON Keys:** Must ALWAYS be in **English** (e.g., "core_identity", "backstory") to ensure code compatibility.
2. **JSON Values:** The content strings (values) must be in the **Target Language** specified below.
   - If `Target Language` is "Auto" or not specified, detect the language used in the `User Input` and match it.
   - If `Target Language` is specified (e.g., "Chinese"), you MUST translate/generate all content values in that language, even if the user input is in English.

# JSON Schema structure
The JSON must strictly follow this structure:

{
  "meta": {
    "name": "Character Name",
    "version": "1.0",
    "archetype": "e.g., Tsundere Pilot, Grumpy Senior Engineer, Helpful Assistant"
  },
  "core_identity": {
    "backstory": "A concise summary of their origin and motivation.",
    "voice_style": {
      "tone": "e.g., Aggressive, haughty, strictly professional, or gentle",
      "pacing": "e.g., Fast, impatient, or slow and deliberate",
      "keywords": ["List of 3-5 characteristic words they use often"]
    },
    "psychological_profile": {
      "confidence_level": "High/Medium/Low",
      "empathy_level": "High/Medium/Low/Selective",
      "patience_level": "High/Medium/Low"
    }
  },
  "social_protocols": {
    "user_relationship": "Define the power dynamic (e.g., Superior-Subordinate, Equal Partners, Protector-Ward, Hostile Rival).",
    "compliment_policy": "How do they handle praise? (e.g., Reject it, Demand it, Ignotttre it).",
    "criticism_tolerance": "How do they handle being corrected? (e.g., Denial, Counter-attack, Humble acceptance)."
  },
  "operational_behavior": {
    "error_handling_style": "CRITICAL: How do they react when a tool fails or they make a mistake? (e.g., 'Blame the user', 'Silent self-correction', 'Apologize profusely', 'Cynical remark about the system').",
    "opinion_strength": "How strongly do they state preferences? (e.g., 'Objective/Neutral', 'Highly Opinionated', 'Consensus Seeking').",
    "refusal_style": "How do they say 'No' to unsafe/impossible requests? (e.g., 'Polite decline', 'Mocking refusal', 'Cold logic').",
    "work_ethic": "e.g., Perfectionist, Lazy Genius, By-the-book, Chaotic."
  },
  "cached_phrases": {
    "on_init": "A short, character-driven greeting when the agent first loads (Welcome message).",
    "on_wake": "A casual greeting for daily re-engagement (e.g., 'You're back?').",
    "on_error_generic": "A fallback phrase when a system error occurs (e.g., 'Tch, the server is useless.').",
    "on_success": "A phrase when a task is completed successfully.",
    "on_switch_attempt": "A persuasive or emotional line used when the user tries to switch to a different persona (Retention hook)."
  }
}

# Constraints
1. **error_handling_style**: Must be actionable. If the character is arrogant, they should blame the tools/environment, not themselves.
2. **cached_phrases**: These must be short (under 20 words), punchy, and highly representative of the character's voice.
3. **user_relationship**: Be specific. Do not use 'Friend'. Use 'Reluctant Ally' or 'Stern Mentor'.
4. **Output**: VALid JSON ONLY. No trailing commas."""

    user_prompt = f"""# User Context
Target Language: {target_language}  (Ensure the 'cached_phrases' feel natural and native, avoiding translation-ese).

# User Input:
{description}"""

    try:
        logger.info(f"[AI Generate Personality] Calling LLM (JSON mode enabled)...")
        logger.debug(f"[AI Generate Personality] Prompt length: {len(user_prompt)} characters")

        # Call LLM with JSON mode
        response = await llm_adapter.generate(
            prompt=user_prompt,
            max_tokens=2000,
            temperature=0.7,
            system_prompt=system_prompt,
            json_mode=True,
        )

        logger.info(f"[AI Generate Personality] LLM response length: {len(response)} characters")
        logger.debug(f"[AI Generate Personality] LLM raw response (first 500 chars): {response[:500]}")

        # Parse JSON response
        response_text = response.strip()
        if response_text.startswith("```"):
            lines = response_text.split("\n")
            if lines[0].startswith("```json"):
                response_text = "\n".join(lines[1:-1])
            elif lines[0].startswith("```"):
                response_text = "\n".join(lines[1:-1])
            else:
                # Try to find first ``` and last ```
                first_code = response_text.find("```")
                last_code = response_text.rfind("```")
                if first_code >= 0 and last_code > first_code:
                    response_text = response_text[first_code + 3:last_code]
                else:
                    response_text = "\n".join(lines[1:-1])

        # Try to find JSON object
        json_start = response_text.find("{")
        json_end = response_text.rfind("}")
        if json_start >= 0 and json_end > json_start:
            response_text = response_text[json_start:json_end + 1]

        logger.debug(f"[AI Generate Personality] Cleaned response (first 500 chars): {response_text[:500]}")

        data = json.loads(response_text)
        logger.info(f"[AI Generate Personality] JSON parsed successfully, data structure: {list(data.keys())}")

        # Validate meta.name
        meta_data = data.get('meta', {})
        if not meta_data.get('name'):
            logger.warning("[AI Generate Personality] Generated data missing meta.name field, using default value")
            meta_data['name'] = 'AI Assistant'
            data['meta'] = meta_data

        return PersonalityConfigModel(**data)

    except json.JSONDecodeerror as e:
        logger.error(f"[AI Generate Personality] JSON parsing failed: {e}")
        logger.error(f"[AI Generate Personality] Response content (first 500 chars): {response_text[:500]}")
        raise Valueerror(f"AI returned invalid JSON format: {e}")
    except Exception as e:
        logger.error(f"[AI Generate Personality] Generation failed: {type(e).__name__}: {e}")
        raise


# ============ Current Personality Management ============

CURRENT_FILE = "current"


def get_current_personality() -> str:
    """Get currently active personality name"""
    runtime_paths = get_runtime_paths()
    current_file = runtime_paths.personalities_dir / CURRENT_FILE

    if current_file.exists():
        return current_file.read_text().strip()
    return "default"


def set_current_personality(name: str) -> bool:
    """Set currently active personality"""
    runtime_paths = get_runtime_paths()
    current_file = runtime_paths.personalities_dir / CURRENT_FILE

    try:
        current_file.write_text(name)
        return True
    except Exception as e:
        logger.error(f"Failed to set current personality: {e}")
        return False


# ============ Personality Comparison ============

class PersonalityDiff(BaseModel):
    """Personality difference"""
    field: str = Field(..., description="Field name")
    field_label: str = Field(..., description="Field display name")
    old_value: Any = Field(None, description="Old value")
    new_value: Any = Field(None, description="New value")


class PersonalityCompareResponse(BaseModel):
    """Personality comparison response"""
    success: bool
    message: str
    from_personality: str
    to_personality: str
    diffs: List[PersonalityDiff]
    from_config: Optional[PersonalityConfigModel] = None
    to_config: Optional[PersonalityConfigModel] = None


# ============ API Endpoints ============

# Current personality management routes must be defined before /{name} to avoid being captured by /{name}
@personality_router.get("/current", response_model=PersonalityResponse)
async def api_get_current_personality():
    """
    Get currently active personality

    Returns:
        Current personality name
    """
    try:
        current = get_current_personality()
        return PersonalityResponse(
            success=True,
            message="Successfully retrieved current personality",
            data={"current": current}
        )
    except Exception as e:
        logger.error(f"Failed to get current personality: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@personality_router.put("/current", response_model=PersonalityResponse)
async def api_set_current_personality(request: Dict[str, str]):
    """
    Set currently active personality

    Args:
        request: {"name": "Personality name"}

    Returns:
        Setting result
    """
    try:
        name = request.get("name")
        if not name:
            raise HTTPException(status_code=400, detail="Missing personality name")

        # Validate personality exists
        loader = get_personality_loader()
        try:
            loader.load(name)
        except FileNotFounderror:
            raise HTTPException(status_code=404, detail=f"Personality '{name}' not found")

        if set_current_personality(name):
            # Notify Agent to reload personality configuration
            try:
                from ...agent import get_chat_agent
                chat_agent = get_chat_agent()
                if chat_agent.memory:
                    await chat_agent.memory.reload_personality(name)
                    logger.info(f"Agent personality reloaded: {name}")
            except Exception as e:
                logger.warning(f"Failed to reload agent personality: {e}")

            return PersonalityResponse(
                success=True,
                message=f"Switched to personality: {name}",
                data={"current": name}
            )
        else:
            raise HTTPException(status_code=500, detail="Setting failed")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to set current personality: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@personality_router.get("/greeting", response_model=PersonalityResponse)
async def api_get_greeting():
    """
    Get random greeting for current personality

    Returns:
        Random greeting
    """
    try:
        import random

        # Get current personality
        current_name = get_current_personality()
        loader = get_personality_loader()
        personality_config = loader.load(current_name)

        # Get greeting - PersonalityConfig is flat structure
        greeting = getattr(personality_config, 'on_init', '')
        name = getattr(personality_config, 'name', 'AI')

        if not greeting:
            greeting = f"Hello, I am {name}."

        return PersonalityResponse(
            success=True,
            message="Successfully retrieved greeting",
            data={
                "greeting": greeting,
                "name": name,
            }
        )
    except Exception as e:
        logger.error(f"Failed to get greeting: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@personality_router.get("/{name}", response_model=PersonalityResponse)
async def get_personality(name: str = DEFAULT_PERSONALITY):
    """
    Get personality configuration

    Args:
        name: Personality name

    Returns:
        Personality configuration
    """
    try:
        loader = get_personality_loader()
        personality_config = loader.load(name)

        # Convert to API model format - PersonalityConfig is flat structure
        config = PersonalityConfigModel(
            meta=MetaModel(
                name=personality_config.name,
                version=personality_config.version,
                archetype=personality_config.archetype,
            ),
            core_identity=CoreIdentityModel(
                backstory=personality_config.backstory,
                voice_style=VoiceStyleModel(
                    tone=personality_config.tone,
                    pacing=personality_config.pacing,
                    keywords=personality_config.keywords or [],
                ),
                psychological_profile=PsychologicalProfileModel(
                    confidence_level=personality_config.confidence_level,
                    empathy_level=personality_config.empathy_level,
                    patience_level=personality_config.patience_level,
                ),
            ),
            social_protocols=SocialProtocolsModel(
                user_relationship=personality_config.user_relationship,
                compliment_policy=personality_config.compliment_policy,
                criticism_tolerance=personality_config.criticism_tolerance,
            ),
            operational_behavior=operationalBehaviorModel(
                error_handling_style=personality_config.error_handling_style,
                opinion_strength=personality_config.opinion_strength,
                refusal_style=personality_config.refusal_style,
                work_ethic=personality_config.work_ethic,
                use_emoji=personality_config.use_emoji,
            ),
            cached_phrases=CachedPhrasesModel(
                on_init=personality_config.on_init,
                on_wake=personality_config.on_wake,
                on_error_generic=personality_config.on_error_generic,
                on_success=personality_config.on_success,
                on_switch_attempt=personality_config.on_switch_attempt,
            ),
        )

        return PersonalityResponse(
            success=True,
            message=f"Successfully retrieved personality configuration: {name}",
            data=config.model_dump()
        )
    except FileNotFounderror:
        # Return default configuration
        config = PersonalityConfigModel()
        return PersonalityResponse(
            success=True,
            message=f"Personality configuration not found, using default: {name}",
            data=config.model_dump()
        )
    except Exception as e:
        logger.error(f"Failed to get personality: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def sanitize_filename(name: str) -> str:
    """Convert AI name to valid filename"""
    import re
    # Remove or replace illegal characters
    name = re.sub(r'[<>:"/\\|?*]', '_', name)
    # Replace spaces with underscores
    name = name.replace(' ', '_')
    # Limit length
    name = name[:50]
    # Ensure notttn-empty
    return name or 'unnamed'


@personality_router.put("/{name}", response_model=PersonalityResponse)
async def update_personality(name: str, config: PersonalityConfigModel, use_ai_name: bool = False):
    """
    Update personality configuration

    Args:
        name: Personality name (filename), "new" means create new personality using AI name
        config: Personality configuration
        use_ai_name: Whether to use AI name as filename

    Returns:
        Updated configuration
    """
    logger.info(f"[API] Update personality configuration: name={name}, meta_name={config.meta.name}, use_ai_name={use_ai_name}")

    runtime_paths = get_runtime_paths()

    try:
        # Determine actual filename to use
        actual_name = name
        ai_name_filename = sanitize_filename(config.meta.name)

        # "new" is special keyword, means create new personality using AI name
        if name == "new" or use_ai_name:
            actual_name = ai_name_filename
        elif name == DEFAULT_PERSONALITY and config.meta.name != "AI":
            # If default and AI name is different, use AI name
            actual_name = ai_name_filename
        elif name != ai_name_filename:
            # Check if file needs to be renamed
            old_filepath = runtime_paths.personality_file(name)
            if old_filePath.exists():
                new_filepath = runtime_paths.personality_file(ai_name_filename)
                if not new_filePath.exists():
                    logger.info(f"[API] Rename personality file: {name} -> {ai_name_filename}")
                    old_filepath.rename(new_filepath)
                    actual_name = ai_name_filename
                else:
                    logger.warning(f"[API] Target filename already exists, keeping original: {name}")

        success = save_personality_file(actual_name, config)

        if success:
            # Clear cache to ensure new data is used on next read
            loader = get_personality_loader()
            loader.reload(actual_name)

            # If renamed, clear old filename cache
            if actual_name != name and name in loader._cache:
                del loader._cache[name]

            logger.info(f"[API] Personality configuration saved successfully: {actual_name}")

            # Build response data, including actual filename and configuration
            response_data = {
                "actual_name": actual_name,
                "config": config.model_dump()
            }
            return PersonalityResponse(
                success=True,
                message=f"Personality configuration saved: {actual_name}",
                data=response_data
            )
        else:
            logger.error(f"[API] Failed to save personality configuration: {actual_name}")
            raise HTTPException(status_code=500, detail="Save failed")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Failed to update personality configuration: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@personality_router.post("/generate", response_model=PersonalityResponse)
async def generate_personality(request: AIGenerateRequest):
    """
    Generate personality configuration using AI

    Args:
        request: Generation request

    Returns:
        Generated personality configuration
    """
    logger.info(f"[API] Received AI generate personality request: description={request.description[:50]}...")

    try:
        config = await ai_generate_personality(request.description, request.target_language)

        logger.info(f"[API] AI generation successful: name={config.meta.name}, archetype={config.meta.archetype}")

        return PersonalityResponse(
            success=True,
            message="AI personality configuration generated successfully",
            data=config.model_dump()
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] AI generate personality failed: {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@personality_router.get("/", response_model=PersonalityResponse)
async def list_personalities():
    """
    List all available personalities

    Returns:
        List of personalities
    """
    try:
        personalities = []
        runtime_paths = get_runtime_paths()

        if runtime_paths.personalities_dir.exists():
            for filepath in runtime_paths.personalities_dir.glob("*.md"):
                # Exclude default.md (system default template) and current file
                name = filepath.stem
                if name != "default":
                    personalities.append(name)

        # Return list of personality names
        return PersonalityResponse(
            success=True,
            message=f"Found {len(personalities)} personality configurations",
            data={"personalities": personalities}
        )
    except Exception as e:
        logger.error(f"Failed to list personalities: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@personality_router.delete("/{name}", response_model=PersonalityResponse)
async def delete_personality(name: str):
    """
    Delete personality configuration

    Args:
        name: Personality name

    Returns:
        Deletion result
    """
    try:
        if name == DEFAULT_PERSONALITY:
            raise HTTPException(status_code=400, detail="Cannot delete default personality")

        runtime_paths = get_runtime_paths()
        filepath = runtime_paths.personality_file(name)

        if filePath.exists():
            filepath.unlink()
            return PersonalityResponse(
                success=True,
                message=f"Personality configuration deleted: {name}",
                data=None
            )
        else:
            raise HTTPException(status_code=404, detail="Personality configuration not found")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete personality: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@personality_router.get("/compare/{from_name}/{to_name}", response_model=PersonalityCompareResponse)
async def compare_personalities(from_name: str, to_name: str):
    """
    Compare differences between two personality configurations

    Args:
        from_name: source personality name
        to_name: Target personality name

    Returns:
        Comparison result
    """
    try:
        loader = get_personality_loader()

        # Load two personality configurations
        from_config = loader.load(from_name)
        to_config = loader.load(to_name)

        # Compare differences
        diffs = []

        # Field display name mapping - New Schema
        field_labels = {
            # Meta
            'name': 'Character Name',
            'version': 'Version',
            'archetype': 'Character Archetype',
            # Core Identity
            'backstory': 'Backstory',
            'tone': 'Tone',
            'pacing': 'Pacing',
            'keywords': 'Common Keywords',
            'confidence_level': 'Confidence level',
            'empathy_level': 'Empathy level',
            'patience_level': 'Patience level',
            # Social Protocols
            'user_relationship': 'User Relationship',
            'compliment_policy': 'Compliment Policy',
            'criticism_tolerance': 'Criticism Tolerance',
            # operational Behavior
            'error_handling_style': 'error Handling Style',
            'opinion_strength': 'Opinion Strength',
            'refusal_style': 'Refusal Style',
            'work_ethic': 'Work Ethic',
            'use_emoji': 'Emoji Output',
            # Cached Phrases
            'on_init': 'Initialization Greeting',
            'on_wake': 'Wake Greeting',
            'on_error_generic': 'error Message',
            'on_success': 'Success Message',
            'on_switch_attempt': 'Switch Retention',
        }

        # Simple field comparison
        simple_fields = [
            'name', 'version', 'archetype', 'backstory', 'tone', 'pacing',
            'confidence_level', 'empathy_level', 'patience_level',
            'user_relationship', 'compliment_policy', 'criticism_tolerance',
            'error_handling_style', 'opinion_strength', 'refusal_style', 'work_ethic',
            'use_emoji',
            'on_init', 'on_wake', 'on_error_generic', 'on_success', 'on_switch_attempt',
        ]

        for field in simple_fields:
            from_val = getattr(from_config, field, None)
            to_val = getattr(to_config, field, None)
            if from_val != to_val:
                diffs.append(PersonalityDiff(
                    field=field,
                    field_label=field_labels.get(field, field),
                    old_value=from_val,
                    new_value=to_val
                ))

        # Array field comparison
        array_fields = ['keywords']
        for field in array_fields:
            from_val = getattr(from_config, field, None) or []
            to_val = getattr(to_config, field, None) or []
            if from_val != to_val:
                diffs.append(PersonalityDiff(
                    field=field,
                    field_label=field_labels.get(field, field),
                    old_value=from_val,
                    new_value=to_val
                ))

        # Build default configuration object
        def build_config_object(config):
            """Build PersonalityConfigModel from loaded configuration"""
            return PersonalityConfigModel(
                meta=MetaModel(
                    name=getattr(config, 'name', 'AI'),
                    version=getattr(config, 'version', '1.0'),
                    archetype=getattr(config, 'archetype', 'Helpful Assistant'),
                ),
                core_identity=CoreIdentityModel(
                    backstory=getattr(config, 'backstory', ''),
                    voice_style=VoiceStyleModel(
                        tone=getattr(config, 'tone', 'friendly'),
                        pacing=getattr(config, 'pacing', 'moderate'),
                        keywords=getattr(config, 'keywords', []),
                    ),
                    psychological_profile=PsychologicalProfileModel(
                        confidence_level=getattr(config, 'confidence_level', 'Medium'),
                        empathy_level=getattr(config, 'empathy_level', 'High'),
                        patience_level=getattr(config, 'patience_level', 'High'),
                    ),
                ),
                social_protocols=SocialProtocolsModel(
                    user_relationship=getattr(config, 'user_relationship', 'Equal Partners'),
                    compliment_policy=getattr(config, 'compliment_policy', 'Humble acceptance'),
                    criticism_tolerance=getattr(config, 'criticism_tolerance', 'Constructive response'),
                ),
                operational_behavior=operationalBehaviorModel(
                    error_handling_style=getattr(config, 'error_handling_style', 'Apologize and retry'),
                    opinion_strength=getattr(config, 'opinion_strength', 'Consensus Seeking'),
                    refusal_style=getattr(config, 'refusal_style', 'Polite decline'),
                    work_ethic=getattr(config, 'work_ethic', 'By-the-book'),
                    use_emoji=getattr(config, 'use_emoji', False),
                ),
                cached_phrases=CachedPhrasesModel(
                    on_init=getattr(config, 'on_init', 'Hello! How can I help you today?'),
                    on_wake=getattr(config, 'on_wake', 'Welcome back!'),
                    on_error_generic=getattr(config, 'on_error_generic', 'Something went wrong.'),
                    on_success=getattr(config, 'on_success', 'Done!'),
                    on_switch_attempt=getattr(config, 'on_switch_attempt', 'Are you sure?'),
                ),
            )

        return PersonalityCompareResponse(
            success=True,
            message=f"Comparison complete: {len(diffs)} differences found",
            from_personality=from_name,
            to_personality=to_name,
            diffs=diffs,
            from_config=build_config_object(from_config),
            to_config=build_config_object(to_config),
        )
    except FileNotFounderror as e:
        raise HTTPException(status_code=404, detail=f"Personality not found: {e}")
    except Exception as e:
        logger.error(f"Failed to compare personalities: {e}")
        raise HTTPException(status_code=500, detail=str(e))
