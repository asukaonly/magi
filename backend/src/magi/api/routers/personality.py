"""
人格配置API路由

提供AI人格的读取、更新和AI生成功能
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

# ============ 数据模型 ============

class MetaModel(BaseModel):
    """元数据"""
    name: str = Field(default="AI", description="角色名称")
    version: str = Field(default="1.0", description="版本号")
    archetype: str = Field(default="Helpful Assistant", description="角色原型")


class VoiceStyleModel(BaseModel):
    """声音风格"""
    tone: str = Field(default="friendly", description="语调")
    pacing: str = Field(default="moderate", description="语速节奏")
    keywords: List[str] = Field(default_factory=list, description="常用词汇")


class PsychologicalProfileModel(BaseModel):
    """心理特征"""
    confidence_level: str = Field(default="Medium", description="自信水平")
    empathy_level: str = Field(default="High", description="共情水平")
    patience_level: str = Field(default="High", description="耐心水平")


class CoreIdentityModel(BaseModel):
    """核心身份"""
    backstory: str = Field(default="", description="背景故事")
    voice_style: VoiceStyleModel = Field(default_factory=VoiceStyleModel)
    psychological_profile: PsychologicalProfileModel = Field(default_factory=PsychologicalProfileModel)


class SocialProtocolsModel(BaseModel):
    """社交协议"""
    user_relationship: str = Field(default="Equal Partners", description="用户关系")
    compliment_policy: str = Field(default="Humble acceptance", description="赞美反应")
    criticism_tolerance: str = Field(default="Constructive response", description="批评容忍度")


class OperationalBehaviorModel(BaseModel):
    """操作行为"""
    error_handling_style: str = Field(default="Apologize and retry", description="错误处理风格")
    opinion_strength: str = Field(default="Consensus Seeking", description="意见强度")
    refusal_style: str = Field(default="Polite decline", description="拒绝风格")
    work_ethic: str = Field(default="By-the-book", description="职业道德")
    use_emoji: bool = Field(default=False, description="是否使用Emoji输出")


class CachedPhrasesModel(BaseModel):
    """缓存短语"""
    on_init: str = Field(default="Hello! How can I help you today?", description="初始化问候")
    on_wake: str = Field(default="Welcome back!", description="唤醒问候")
    on_error_generic: str = Field(default="Something went wrong. Let me try again.", description="错误提示")
    on_success: str = Field(default="Done! Is there anything else?", description="成功提示")
    on_switch_attempt: str = Field(default="Are you sure you want to switch?", description="切换挽留")


class PersonalityConfigModel(BaseModel):
    """完整人格配置 - 新Schema"""
    meta: MetaModel = Field(default_factory=MetaModel)
    core_identity: CoreIdentityModel = Field(default_factory=CoreIdentityModel)
    social_protocols: SocialProtocolsModel = Field(default_factory=SocialProtocolsModel)
    operational_behavior: OperationalBehaviorModel = Field(default_factory=OperationalBehaviorModel)
    cached_phrases: CachedPhrasesModel = Field(default_factory=CachedPhrasesModel)


class AIGenerateRequest(BaseModel):
    """AI生成请求"""
    description: str = Field(..., description="一句话描述AI人格")
    target_language: str = Field(default="Auto", description="目标语言：Auto/Chinese/English等")
    current_config: Optional[PersonalityConfigModel] = Field(None, description="当前配置（可选）")


class PersonalityResponse(BaseModel):
    """人格配置响应"""
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None  # 支持多种数据类型


# ============ 配置存储路径 ============

DEFAULT_PERSONALITY = "default"


# ============ 辅助函数 ============

def get_personality_loader() -> PersonalityLoader:
    """获取人格加载器实例（使用运行时目录）"""
    runtime_paths = get_runtime_paths()
    return PersonalityLoader(str(runtime_paths.personalities_dir))


def save_personality_file(name: str, config: PersonalityConfigModel) -> bool:
    """保存人格配置到Markdown文件"""
    try:
        runtime_paths = get_runtime_paths()
        runtime_paths.personalities_dir.mkdir(parents=True, exist_ok=True)

        # 辅助函数：格式化数组
        def format_array(items: List[str]) -> str:
            if not items:
                return '[]'
            return '[' + ', '.join(f'"{item}"' for item in items) + ']'

        content = f"""# AI 人格配置 - {config.meta.name}

## 元数据
- name: {config.meta.name}
- version: {config.meta.version}
- archetype: {config.meta.archetype}

## 核心身份

### 背景故事
- backstory: |
  {config.core_identity.backstory}

### 声音风格
- tone: {config.core_identity.voice_style.tone}
- pacing: {config.core_identity.voice_style.pacing}
- keywords: {format_array(config.core_identity.voice_style.keywords)}

### 心理特征
- confidence_level: {config.core_identity.psychological_profile.confidence_level}
- empathy_level: {config.core_identity.psychological_profile.empathy_level}
- patience_level: {config.core_identity.psychological_profile.patience_level}

## 社交协议
- user_relationship: {config.social_protocols.user_relationship}
- compliment_policy: {config.social_protocols.compliment_policy}
- criticism_tolerance: {config.social_protocols.criticism_tolerance}

## 操作行为
- error_handling_style: {config.operational_behavior.error_handling_style}
- opinion_strength: {config.operational_behavior.opinion_strength}
- refusal_style: {config.operational_behavior.refusal_style}
- work_ethic: {config.operational_behavior.work_ethic}
- use_emoji: {str(config.operational_behavior.use_emoji).lower()}

## 缓存短语
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


# ============ LLM解析函数 ============

async def ai_generate_personality(description: str, target_language: str = "Auto") -> PersonalityConfigModel:
    """使用LLM从描述生成人格配置"""
    import os
    import json
    from ...llm.openai import OpenAIAdapter

    logger.info(f"[AI生成人格] 开始处理描述: {description[:100]}...")
    logger.info(f"[AI生成人格] 目标语言: {target_language}")

    # 获取LLM配置
    provider = (os.getenv("LLM_PROVIDER") or "openai").lower()
    api_key = os.getenv("LLM_API_KEY")
    model = os.getenv("LLM_MODEL", "gpt-4")
    base_url = os.getenv("LLM_BASE_URL")

    logger.info(f"[AI生成人格] LLM配置: model={model}, base_url={base_url}")

    if not api_key:
        logger.error("[AI生成人格] LLM_API_KEY not configured")
        raise ValueError("LLM_API_KEY not configured")

    # 创建LLM适配器
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

# JSON Schema Structure
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
    "compliment_policy": "How do they handle praise? (e.g., Reject it, Demand it, Ignore it).",
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
4. **Output**: VALID JSON ONLY. No trailing commas."""

    user_prompt = f"""# User Context
Target Language: {target_language}  (Ensure the 'cached_phrases' feel natural and native, avoiding translation-ese).

# User Input:
{description}"""

    try:
        logger.info(f"[AI生成人格] 调用LLM（JSON模式已启用）...")
        logger.debug(f"[AI生成人格] Prompt长度: {len(user_prompt)} 字符")

        # 调用LLM with JSON mode
        response = await llm_adapter.generate(
            prompt=user_prompt,
            max_tokens=2000,
            temperature=0.7,
            system_prompt=system_prompt,
            json_mode=True,
        )

        logger.info(f"[AI生成人格] LLM响应长度: {len(response)} 字符")
        logger.debug(f"[AI生成人格] LLM原始响应 (前500字符): {response[:500]}")

        # 解析JSON响应
        response_text = response.strip()
        if response_text.startswith("```"):
            lines = response_text.split("\n")
            if lines[0].startswith("```json"):
                response_text = "\n".join(lines[1:-1])
            elif lines[0].startswith("```"):
                response_text = "\n".join(lines[1:-1])
            else:
                # 尝试找到第一个```和最后一个```
                first_code = response_text.find("```")
                last_code = response_text.rfind("```")
                if first_code >= 0 and last_code > first_code:
                    response_text = response_text[first_code + 3:last_code]
                else:
                    response_text = "\n".join(lines[1:-1])

        # 尝试找到JSON对象
        json_start = response_text.find("{")
        json_end = response_text.rfind("}")
        if json_start >= 0 and json_end > json_start:
            response_text = response_text[json_start:json_end + 1]

        logger.debug(f"[AI生成人格] 清理后响应 (前500字符): {response_text[:500]}")

        data = json.loads(response_text)
        logger.info(f"[AI生成人格] 解析JSON成功, 数据结构: {list(data.keys())}")

        # 验证 meta.name
        meta_data = data.get('meta', {})
        if not meta_data.get('name'):
            logger.warning("[AI生成人格] 生成的数据缺少meta.name字段，使用默认值")
            meta_data['name'] = 'AI助手'
            data['meta'] = meta_data

        return PersonalityConfigModel(**data)

    except json.JSONDecodeError as e:
        logger.error(f"[AI生成人格] JSON解析失败: {e}")
        logger.error(f"[AI生成人格] 响应内容 (前500字符): {response_text[:500]}")
        raise ValueError(f"AI返回的不是有效的JSON格式: {e}")
    except Exception as e:
        logger.error(f"[AI生成人格] 生成失败: {type(e).__name__}: {e}")
        raise


# ============ Current人格管理 ============

CURRENT_FILE = "current"


def get_current_personality() -> str:
    """获取当前激活的人格名称"""
    runtime_paths = get_runtime_paths()
    current_file = runtime_paths.personalities_dir / CURRENT_FILE

    if current_file.exists():
        return current_file.read_text().strip()
    return "default"


def set_current_personality(name: str) -> bool:
    """设置当前激活的人格"""
    runtime_paths = get_runtime_paths()
    current_file = runtime_paths.personalities_dir / CURRENT_FILE

    try:
        current_file.write_text(name)
        return True
    except Exception as e:
        logger.error(f"Failed to set current personality: {e}")
        return False


# ============ 人格比较 ============

class PersonalityDiff(BaseModel):
    """人格差异"""
    field: str = Field(..., description="字段名称")
    field_label: str = Field(..., description="字段显示名称")
    old_value: Any = Field(None, description="原值")
    new_value: Any = Field(None, description="新值")


class PersonalityCompareResponse(BaseModel):
    """人格比较响应"""
    success: bool
    message: str
    from_personality: str
    to_personality: str
    diffs: List[PersonalityDiff]
    from_config: Optional[PersonalityConfigModel] = None
    to_config: Optional[PersonalityConfigModel] = None


# ============ API端点 ============

# Current 人格管理路由必须在 /{name} 之前定义，避免被 /{name} 捕获
@personality_router.get("/current", response_model=PersonalityResponse)
async def api_get_current_personality():
    """
    获取当前激活的人格

    Returns:
        当前人格名称
    """
    try:
        current = get_current_personality()
        return PersonalityResponse(
            success=True,
            message="获取当前人格成功",
            data={"current": current}
        )
    except Exception as e:
        logger.error(f"Failed to get current personality: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@personality_router.put("/current", response_model=PersonalityResponse)
async def api_set_current_personality(request: Dict[str, str]):
    """
    设置当前激活的人格

    Args:
        request: {"name": "人格名称"}

    Returns:
        设置结果
    """
    try:
        name = request.get("name")
        if not name:
            raise HTTPException(status_code=400, detail="缺少人格名称")

        # 验证人格存在
        loader = get_personality_loader()
        try:
            loader.load(name)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"人格 '{name}' 不存在")

        if set_current_personality(name):
            # 通知 Agent 重新加载人格配置
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
                message=f"已切换到人格: {name}",
                data={"current": name}
            )
        else:
            raise HTTPException(status_code=500, detail="设置失败")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to set current personality: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@personality_router.get("/greeting", response_model=PersonalityResponse)
async def api_get_greeting():
    """
    获取当前人格的随机问候语

    Returns:
        随机问候语
    """
    try:
        import random

        # 获取当前人格
        current_name = get_current_personality()
        loader = get_personality_loader()
        personality_config = loader.load(current_name)

        # 获取问候语 - PersonalityConfig 是扁平结构
        greeting = getattr(personality_config, 'on_init', '')
        name = getattr(personality_config, 'name', 'AI')

        if not greeting:
            greeting = f"你好，我是{name}。"

        return PersonalityResponse(
            success=True,
            message="获取问候语成功",
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
    获取人格配置

    Args:
        name: 人格名称

    Returns:
        人格配置
    """
    try:
        loader = get_personality_loader()
        personality_config = loader.load(name)

        # 转换为API模型格式 - PersonalityConfig 是扁平结构
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
            operational_behavior=OperationalBehaviorModel(
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
            message=f"获取人格配置成功: {name}",
            data=config.model_dump()
        )
    except FileNotFoundError:
        # 返回默认配置
        config = PersonalityConfigModel()
        return PersonalityResponse(
            success=True,
            message=f"人格配置不存在，使用默认值: {name}",
            data=config.model_dump()
        )
    except Exception as e:
        logger.error(f"Failed to get personality: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def sanitize_filename(name: str) -> str:
    """将AI名字转换为合法的文件名"""
    import re
    # 移除或替换非法字符
    name = re.sub(r'[<>:"/\\|?*]', '_', name)
    # 替换空格为下划线
    name = name.replace(' ', '_')
    # 限制长度
    name = name[:50]
    # 确保非空
    return name or 'unnamed'


@personality_router.put("/{name}", response_model=PersonalityResponse)
async def update_personality(name: str, config: PersonalityConfigModel, use_ai_name: bool = False):
    """
    更新人格配置

    Args:
        name: 人格名称（文件名），"new"表示使用AI名字创建新人格
        config: 人格配置
        use_ai_name: 是否使用AI名字作为文件名

    Returns:
        更新后的配置
    """
    logger.info(f"[API] 更新人格配置: name={name}, meta_name={config.meta.name}, use_ai_name={use_ai_name}")

    runtime_paths = get_runtime_paths()

    try:
        # 确定实际使用的文件名
        actual_name = name
        ai_name_filename = sanitize_filename(config.meta.name)

        # "new" 是特殊关键字，表示使用AI名字创建新人格
        if name == "new" or use_ai_name:
            actual_name = ai_name_filename
        elif name == DEFAULT_PERSONALITY and config.meta.name != "AI":
            # 如果是default且AI名字不同，使用AI名字
            actual_name = ai_name_filename
        elif name != ai_name_filename:
            # 检查是否需要重命名文件
            old_filepath = runtime_paths.personality_file(name)
            if old_filepath.exists():
                new_filepath = runtime_paths.personality_file(ai_name_filename)
                if not new_filepath.exists():
                    logger.info(f"[API] 重命名人格文件: {name} -> {ai_name_filename}")
                    old_filepath.rename(new_filepath)
                    actual_name = ai_name_filename
                else:
                    logger.warning(f"[API] 目标文件名已存在，保持原文件名: {name}")

        success = save_personality_file(actual_name, config)

        if success:
            # 清除缓存，确保下次读取时使用新数据
            loader = get_personality_loader()
            loader.reload(actual_name)

            # 如果重命名了，清除旧文件名的缓存
            if actual_name != name and name in loader._cache:
                del loader._cache[name]

            logger.info(f"[API] 人格配置保存成功: {actual_name}")

            # 构建响应数据，包含实际文件名和配置
            response_data = {
                "actual_name": actual_name,
                "config": config.model_dump()
            }
            return PersonalityResponse(
                success=True,
                message=f"人格配置已保存: {actual_name}",
                data=response_data
            )
        else:
            logger.error(f"[API] 人格配置保存失败: {actual_name}")
            raise HTTPException(status_code=500, detail="保存失败")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] 更新人格配置失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@personality_router.post("/generate", response_model=PersonalityResponse)
async def generate_personality(request: AIGenerateRequest):
    """
    使用AI生成人格配置

    Args:
        request: 生成请求

    Returns:
        生成的人格配置
    """
    logger.info(f"[API] 收到AI生成人格请求: description={request.description[:50]}...")

    try:
        config = await ai_generate_personality(request.description, request.target_language)

        logger.info(f"[API] AI生成成功: name={config.meta.name}, archetype={config.meta.archetype}")

        return PersonalityResponse(
            success=True,
            message="AI生成人格配置成功",
            data=config.model_dump()
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] AI生成人格失败: {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@personality_router.get("/", response_model=PersonalityResponse)
async def list_personalities():
    """
    列出所有可用的人格

    Returns:
        人格列表
    """
    try:
        personalities = []
        runtime_paths = get_runtime_paths()

        if runtime_paths.personalities_dir.exists():
            for filepath in runtime_paths.personalities_dir.glob("*.md"):
                # 排除 default.md（系统默认模板）和 current 文件
                name = filepath.stem
                if name != "default":
                    personalities.append(name)

        # 返回人格名称列表
        return PersonalityResponse(
            success=True,
            message=f"找到 {len(personalities)} 个人格配置",
            data={"personalities": personalities}
        )
    except Exception as e:
        logger.error(f"Failed to list personalities: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@personality_router.delete("/{name}", response_model=PersonalityResponse)
async def delete_personality(name: str):
    """
    删除人格配置

    Args:
        name: 人格名称

    Returns:
        删除结果
    """
    try:
        if name == DEFAULT_PERSONALITY:
            raise HTTPException(status_code=400, detail="不能删除默认人格")

        runtime_paths = get_runtime_paths()
        filepath = runtime_paths.personality_file(name)

        if filepath.exists():
            filepath.unlink()
            return PersonalityResponse(
                success=True,
                message=f"人格配置已删除: {name}",
                data=None
            )
        else:
            raise HTTPException(status_code=404, detail="人格配置不存在")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete personality: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@personality_router.get("/compare/{from_name}/{to_name}", response_model=PersonalityCompareResponse)
async def compare_personalities(from_name: str, to_name: str):
    """
    比较两个人格配置的差异

    Args:
        from_name: 源人格名称
        to_name: 目标人格名称

    Returns:
        比较结果
    """
    try:
        loader = get_personality_loader()

        # 加载两个人格配置
        from_config = loader.load(from_name)
        to_config = loader.load(to_name)

        # 比较差异
        diffs = []

        # 字段显示名称映射 - 新Schema
        field_labels = {
            # Meta
            'name': '角色名称',
            'version': '版本',
            'archetype': '角色原型',
            # Core Identity
            'backstory': '背景故事',
            'tone': '语调',
            'pacing': '语速节奏',
            'keywords': '常用词汇',
            'confidence_level': '自信水平',
            'empathy_level': '共情水平',
            'patience_level': '耐心水平',
            # Social Protocols
            'user_relationship': '用户关系',
            'compliment_policy': '赞美反应',
            'criticism_tolerance': '批评容忍度',
            # Operational Behavior
            'error_handling_style': '错误处理风格',
            'opinion_strength': '意见强度',
            'refusal_style': '拒绝风格',
            'work_ethic': '职业道德',
            'use_emoji': 'Emoji输出',
            # Cached Phrases
            'on_init': '初始化问候',
            'on_wake': '唤醒问候',
            'on_error_generic': '错误提示',
            'on_success': '成功提示',
            'on_switch_attempt': '切换挽留',
        }

        # 简单字段比较
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

        # 数组字段比较
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

        # 构建默认配置对象
        def build_config_object(config):
            """从加载的配置构建 PersonalityConfigModel"""
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
                operational_behavior=OperationalBehaviorModel(
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
            message=f"比较完成: {len(diffs)} 处不同",
            from_personality=from_name,
            to_personality=to_name,
            diffs=diffs,
            from_config=build_config_object(from_config),
            to_config=build_config_object(to_config),
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=f"人格不存在: {e}")
    except Exception as e:
        logger.error(f"Failed to compare personalities: {e}")
        raise HTTPException(status_code=500, detail=str(e))
