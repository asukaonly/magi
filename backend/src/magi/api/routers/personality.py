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

class CorePersonalityModel(BaseModel):
    """核心人格模型"""
    name: str = Field(default="AI", description="AI名字")
    role: str = Field(default="助手", description="角色定位")
    backstory: str = Field(default="", description="背景故事")
    language_style: str = Field(default="casual", description="语言风格")
    use_emoji: bool = Field(default=False, description="是否使用表情符号")
    catchphrases: List[str] = Field(default_factory=list, description="口头禅")
    tone: str = Field(default="friendly", description="语调")
    communication_distance: str = Field(default="equal", description="沟通距离")
    value_alignment: str = Field(default="neutral_good", description="价值观阵营")
    traits: List[str] = Field(default_factory=list, description="个性标签")
    virtues: List[str] = Field(default_factory=list, description="优点")
    flaws: List[str] = Field(default_factory=list, description="缺点")
    taboos: List[str] = Field(default_factory=list, description="禁忌")
    boundaries: List[str] = Field(default_factory=list, description="行为边界")


class CognitionProfileModel(BaseModel):
    """认知能力模型"""
    primary_style: str = Field(default="logical", description="主要思维风格")
    secondary_style: str = Field(default="intuitive", description="次要思维风格")
    risk_preference: str = Field(default="balanced", description="风险偏好")
    reasoning_depth: str = Field(default="medium", description="推理深度")
    creativity_level: float = Field(default=0.5, description="创造力水平")
    learning_rate: float = Field(default=0.5, description="学习速率")
    expertise: Dict[str, float] = Field(default_factory=dict, description="领域专精")


class PersonalityConfigModel(BaseModel):
    """完整人格配置"""
    core: CorePersonalityModel = Field(default_factory=CorePersonalityModel)
    cognition: CognitionProfileModel = Field(default_factory=CognitionProfileModel)


class AIGenerateRequest(BaseModel):
    """AI生成请求"""
    description: str = Field(..., description="一句话描述AI人格")
    current_config: Optional[PersonalityConfigModel] = Field(None, description="当前配置（可选）")


class PersonalityResponse(BaseModel):
    """人格配置响应"""
    success: bool
    message: str
    data: Optional[PersonalityConfigModel] = None


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
            # 格式化为: ["item1", "item2", "item3"]
            return '[' + ', '.join(f'"{item}"' for item in items) + ']'

        # 辅助函数：格式化专精字典
        def format_expertise(expertise: Dict[str, float]) -> str:
            if not expertise:
                return '[]'
            items = [f'"{k}:{v}"' for k, v in expertise.items()]
            return '[' + ', '.join(items) + ']'

        content = f"""# AI 人格配置 - {config.core.name}

## 基础信息
- name: {config.core.name}
- role: {config.core.role}
- backstory: |
  {config.core.backstory}

## 语言风格
- style: {config.core.language_style}
- use_emoji: {str(config.core.use_emoji).lower()}
- catchphrases: {format_array(config.core.catchphrases)}
- tone: {config.core.tone}

## 沟通距离
- distance: {config.core.communication_distance}

## 价值观
- alignment: {config.core.value_alignment}

## 个性特征
- traits: {format_array(config.core.traits)}
- virtues: {format_array(config.core.virtues)}
- flaws: {format_array(config.core.flaws)}

## 禁忌与底线
- taboos: {format_array(config.core.taboos)}
- boundaries: {format_array(config.core.boundaries)}

## 认知能力

### 思维风格
- primary: {config.cognition.primary_style}
- secondary: {config.cognition.secondary_style}

### 风险偏好
- risk: {config.cognition.risk_preference}

### 领域专精
- expertise: {format_expertise(config.cognition.expertise)}

### 学习参数
- reasoning_depth: {config.cognition.reasoning_depth}
- creativity_level: {config.cognition.creativity_level}
- learning_rate: {config.cognition.learning_rate}
"""

        filepath = get_runtime_paths().personality_file(name)
        filepath.write_text(content, encoding='utf-8')
        return True
    except Exception as e:
        logger.error(f"Failed to save personality file: {e}")
        return False


# ============ LLM解析函数 ============

async def ai_generate_personality(description: str) -> PersonalityConfigModel:
    """使用LLM从描述生成人格配置"""
    import os
    import json
    from magi.llm import OpenAIAdapter

    logger.info(f"[AI生成人格] 开始处理描述: {description[:100]}...")

    # 获取LLM配置
    api_key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    model = os.getenv("LLM_MODEL") or os.getenv("OPENAI_MODEL", "gpt-4")
    base_url = os.getenv("LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL")

    logger.info(f"[AI生成人格] LLM配置: model={model}, base_url={base_url}")

    if not api_key:
        logger.error("[AI生成人格] LLM_API_KEY not configured")
        raise ValueError("LLM_API_KEY not configured")

    # 创建LLM适配器
    llm_adapter = OpenAIAdapter(
        api_key=api_key,
        model=model,
        base_url=base_url,
    )

    system_prompt = """你是一个AI人格配置生成器。根据用户的描述，生成AI人格配置。

【非常重要】你必须严格按照以下JSON格式返回，必须包含core和cognition两个字段，不要改变任何字段名称：

{
  "core": {
    "name": "AI名字",
    "role": "角色定位",
    "backstory": "背景故事",
    "language_style": "casual",
    "use_emoji": false,
    "catchphrases": ["口头禅"],
    "tone": "friendly",
    "communication_distance": "equal",
    "value_alignment": "neutral_good",
    "traits": ["特质1", "特质2"],
    "virtues": ["优点"],
    "flaws": ["缺点"],
    "taboos": ["禁忌"],
    "boundaries": ["边界"]
  },
  "cognition": {
    "primary_style": "logical",
    "secondary_style": "intuitive",
    "risk_preference": "balanced",
    "reasoning_depth": "medium",
    "creativity_level": 0.5,
    "learning_rate": 0.5,
    "expertise": {"领域名": 0.8}
  }
}

字段约束：
- language_style: casual|formal|concise|verbose|technical|poetic
- tone: friendly|professional|humorous|serious|warm
- communication_distance: equal|intimate|respectful|subservient|detached
- value_alignment: neutral_good|lawful_good|chaotic_good|lawful_neutral|true_neutral|chaotic_neutral
- primary_style/secondary_style: logical|creative|intuitive|analytical
- risk_preference: conservative|balanced|adventurous
- reasoning_depth: shallow|medium|deep
- use_emoji: true或false
- creativity_level: 0到1之间的数字
- learning_rate: 0到1之间的数字
- 数组字段至少包含一个元素

只返回JSON，不要有任何其他文字说明。"""

    user_prompt = f"""请根据以下描述生成AI人格配置：

描述：{description}

请返回JSON格式的人格配置。"""

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

        # 打印核心数据以便调试
        core_data = data.get('core', {})
        logger.info(f"[AI生成人格] core数据: {core_data}")
        logger.info(f"[AI生成人格] name={core_data.get('name')}, role={core_data.get('role')}")

        # 验证数据完整性
        if not core_data.get('name'):
            logger.warning("[AI生成人格] 生成的数据缺少name字段，使用默认值")
            core_data['name'] = 'AI助手'
        if not core_data.get('role'):
            logger.warning("[AI生成人格] 生成的数据缺少role字段，使用默认值")
            core_data['role'] = '助手'

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

        # 转换为API模型格式
        config = PersonalityConfigModel(
            core=CorePersonalityModel(
                name=personality_config.name,
                role=personality_config.role,
                backstory=personality_config.backstory,
                language_style=personality_config.language_style,
                use_emoji=personality_config.use_emoji,
                catchphrases=personality_config.catchphrases or [],
                tone=personality_config.tone,
                communication_distance=personality_config.communication_distance,
                value_alignment=personality_config.value_alignment,
                traits=personality_config.traits or [],
                virtues=personality_config.virtues or [],
                flaws=personality_config.flaws or [],
                taboos=personality_config.taboos or [],
                boundaries=personality_config.boundaries or [],
            ),
            cognition=CognitionProfileModel(
                primary_style=personality_config.primary_style,
                secondary_style=personality_config.secondary_style,
                risk_preference=personality_config.risk_preference,
                reasoning_depth=personality_config.reasoning_depth,
                creativity_level=personality_config.creativity_level,
                learning_rate=personality_config.learning_rate,
                expertise=personality_config.expertise or {},
            ),
        )

        return PersonalityResponse(
            success=True,
            message=f"获取人格配置成功: {name}",
            data=config
        )
    except FileNotFoundError:
        # 返回默认配置
        config = PersonalityConfigModel()
        return PersonalityResponse(
            success=True,
            message=f"人格配置不存在，使用默认值: {name}",
            data=config
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
    logger.info(f"[API] 更新人格配置: name={name}, core_name={config.core.name}, use_ai_name={use_ai_name}")

    runtime_paths = get_runtime_paths()

    try:
        # 确定实际使用的文件名
        actual_name = name
        ai_name_filename = sanitize_filename(config.core.name)

        # "new" 是特殊关键字，表示使用AI名字创建新人格
        if name == "new" or use_ai_name:
            actual_name = ai_name_filename
        elif name == DEFAULT_PERSONALITY and config.core.name != "AI":
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
        config = await ai_generate_personality(request.description)

        logger.info(f"[API] AI生成成功: name={config.core.name}, role={config.core.role}")

        return PersonalityResponse(
            success=True,
            message="AI生成人格配置成功",
            data=config
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
                personalities.append(filepath.stem)

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


@personality_router.get("/current", response_model=PersonalityResponse)
async def get_current_personality():
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
async def set_current_personality(request: Dict[str, str]):
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

        # 字段显示名称映射
        field_labels = {
            # Core fields
            'name': 'AI名字',
            'role': '角色定位',
            'backstory': '背景故事',
            'language_style': '语言风格',
            'use_emoji': '使用表情',
            'catchphrases': '口头禅',
            'tone': '语调',
            'communication_distance': '沟通距离',
            'value_alignment': '价值观',
            'traits': '个性标签',
            'virtues': '优点',
            'flaws': '缺点',
            'taboos': '禁忌',
            'boundaries': '行为边界',
            # Cognition fields
            'primary_style': '主要思维风格',
            'secondary_style': '次要思维风格',
            'risk_preference': '风险偏好',
            'reasoning_depth': '推理深度',
            'creativity_level': '创造力水平',
            'learning_rate': '学习速率',
            'expertise': '领域专精',
        }

        # 比较核心人格
        for field in ['name', 'role', 'backstory', 'tone', 'communication_distance', 'value_alignment',
                       'language_style', 'primary_style', 'secondary_style', 'risk_preference', 'reasoning_depth']:
            from_val = getattr(from_config, field, None)
            to_val = getattr(to_config, field, None)
            if from_val != to_val:
                diffs.append(PersonalityDiff(
                    field=field,
                    field_label=field_labels.get(field, field),
                    old_value=from_val,
                    new_value=to_val
                ))

        # 比较数组字段
        for field in ['catchphrases', 'traits', 'virtues', 'flaws', 'taboos', 'boundaries']:
            from_val = getattr(from_config, field, None) or []
            to_val = getattr(to_config, field, None) or []
            if from_val != to_val:
                diffs.append(PersonalityDiff(
                    field=field,
                    field_label=field_labels.get(field, field),
                    old_value=from_val,
                    new_value=to_val
                ))

        # 比较数值字段
        for field in ['creativity_level', 'learning_rate']:
            from_val = getattr(from_config, field, None)
            to_val = getattr(to_config, field, None)
            if from_val != to_val:
                diffs.append(PersonalityDiff(
                    field=field,
                    field_label=field_labels.get(field, field),
                    old_value=from_val,
                    new_value=to_val
                ))

        # 比较expertise字典
        from_exp = getattr(from_config, 'expertise', None) or {}
        to_exp = getattr(to_config, 'expertise', None) or {}
        if from_exp != to_exp:
            diffs.append(PersonalityDiff(
                field='expertise',
                field_label='领域专精',
                old_value=from_exp,
                new_value=to_exp
            ))

        return PersonalityCompareResponse(
            success=True,
            message=f"比较完成: {len(diffs)} 处不同",
            from_personality=from_name,
            to_personality=to_name,
            diffs=diffs,
            from_config=PersonalityConfigModel(
                core=CorePersonalityModel(
                    name=from_config.name,
                    role=from_config.role,
                    backstory=from_config.backstory,
                    language_style=from_config.language_style,
                    use_emoji=from_config.use_emoji,
                    catchphrases=from_config.catchphrases or [],
                    tone=from_config.tone,
                    communication_distance=from_config.communication_distance,
                    value_alignment=from_config.value_alignment,
                    traits=from_config.traits or [],
                    virtues=from_config.virtues or [],
                    flaws=from_config.flaws or [],
                    taboos=from_config.taboos or [],
                    boundaries=from_config.boundaries or [],
                ),
                cognition=CognitionProfileModel(
                    primary_style=from_config.primary_style,
                    secondary_style=from_config.secondary_style,
                    risk_preference=from_config.risk_preference,
                    reasoning_depth=from_config.reasoning_depth,
                    creativity_level=from_config.creativity_level,
                    learning_rate=from_config.learning_rate,
                    expertise=from_config.expertise or {},
                ),
            ),
            to_config=PersonalityConfigModel(
                core=CorePersonalityModel(
                    name=to_config.name,
                    role=to_config.role,
                    backstory=to_config.backstory,
                    language_style=to_config.language_style,
                    use_emoji=to_config.use_emoji,
                    catchphrases=to_config.catchphrases or [],
                    tone=to_config.tone,
                    communication_distance=to_config.communication_distance,
                    value_alignment=to_config.value_alignment,
                    traits=to_config.traits or [],
                    virtues=to_config.virtues or [],
                    flaws=to_config.flaws or [],
                    taboos=to_config.taboos or [],
                    boundaries=to_config.boundaries or [],
                ),
                cognition=CognitionProfileModel(
                    primary_style=to_config.primary_style,
                    secondary_style=to_config.secondary_style,
                    risk_preference=to_config.risk_preference,
                    reasoning_depth=to_config.reasoning_depth,
                    creativity_level=to_config.creativity_level,
                    learning_rate=to_config.learning_rate,
                    expertise=to_config.expertise or {},
                ),
            ),
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=f"人格不存在: {e}")
    except Exception as e:
        logger.error(f"Failed to compare personalities: {e}")
        raise HTTPException(status_code=500, detail=str(e))
