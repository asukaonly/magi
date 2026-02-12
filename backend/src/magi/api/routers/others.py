"""
他人记忆API路由

提供用户画像（他人记忆）的查询、更新、删除等功能
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import logging

from ...memory.other_memory import OtherMemory, OtherProfile
from ...utils.runtime import get_runtime_paths

logger = logging.getLogger(__name__)

others_router = APIRouter()

# 全局他人记忆实例
_other_memory: Optional[OtherMemory] = None


def get_other_memory() -> OtherMemory:
    """获取他人记忆实例"""
    global _other_memory
    if _other_memory is None:
        runtime_paths = get_runtime_paths()
        _other_memory = OtherMemory(str(runtime_paths.others_dir))
    return _other_memory


# ============ 数据模型 ============

class UserProfileResponse(BaseModel):
    """用户画像响应"""
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None


class UserProfileListResponse(BaseModel):
    """用户画像列表响应"""
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None


# ============ API端点 ============

@others_router.get("/list", response_model=UserProfileListResponse)
async def list_profiles():
    """
    列出所有用户画像

    Returns:
        用户画像列表
    """
    try:
        other_memory = get_other_memory()
        profiles = other_memory.list_profiles()

        profiles_data = [p.to_dict() for p in profiles]

        return UserProfileListResponse(
            success=True,
            message=f"找到 {len(profiles)} 个用户画像",
            data={
                "profiles": profiles_data,
                "count": len(profiles),
            }
        )
    except Exception as e:
        logger.error(f"Failed to list profiles: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@others_router.get("/{user_id}", response_model=UserProfileResponse)
async def get_profile(user_id: str):
    """
    获取用户画像

    Args:
        user_id: 用户ID

    Returns:
        用户画像
    """
    try:
        other_memory = get_other_memory()
        profile = other_memory.get_profile(user_id)

        if profile is None:
            return UserProfileResponse(
                success=False,
                message=f"用户 {user_id} 的画像不存在",
                data=None
            )

        return UserProfileResponse(
            success=True,
            message="获取成功",
            data=profile.to_dict()
        )
    except Exception as e:
        logger.error(f"Failed to get profile: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@others_router.post("/{user_id}", response_model=UserProfileResponse)
async def update_profile(user_id: str, profile_data: Dict[str, Any]):
    """
    更新用户画像

    Args:
        user_id: 用户ID
        profile_data: 画像数据

    Returns:
        更新结果
    """
    try:
        other_memory = get_other_memory()
        profile = other_memory.get_profile(user_id)

        if profile is None:
            # 创建新画像
            profile = OtherProfile(user_id=user_id, **profile_data)
        else:
            # 更新现有画像
            profile_data["user_id"] = user_id
            profile = OtherProfile.from_dict({**profile.to_dict(), **profile_data})

        success = other_memory.save_profile(profile)

        if success:
            return UserProfileResponse(
                success=True,
                message="用户画像已保存",
                data=profile.to_dict()
            )
        else:
            raise HTTPException(status_code=500, detail="保存失败")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update profile: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@others_router.delete("/{user_id}", response_model=UserProfileResponse)
async def delete_profile(user_id: str):
    """
    删除用户画像

    Args:
        user_id: 用户ID

    Returns:
        删除结果
    """
    try:
        other_memory = get_other_memory()
        success = other_memory.delete_profile(user_id)

        if success:
            return UserProfileResponse(
                success=True,
                message=f"用户 {user_id} 的画像已删除",
                data=None
            )
        else:
            raise HTTPException(status_code=500, detail="删除失败")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete profile: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@others_router.post("/{user_id}/interaction", response_model=UserProfileResponse)
async def record_interaction(user_id: str, interaction: Dict[str, Any]):
    """
    记录交互并更新用户画像

    Args:
        user_id: 用户ID
        interaction: 交互数据
            - interaction_type: 交互类型
            - outcome: 结果（positive/negative/neutral）
            - notes: 备注

    Returns:
        更新后的画像
    """
    try:
        other_memory = get_other_memory()

        profile = other_memory.update_interaction(
            user_id=user_id,
            interaction_type=interaction.get("interaction_type", "chat"),
            outcome=interaction.get("outcome", "neutral"),
            notes=interaction.get("notes", ""),
        )

        return UserProfileResponse(
            success=True,
            message="交互已记录",
            data=profile.to_dict()
        )
    except Exception as e:
        logger.error(f"Failed to record interaction: {e}")
        raise HTTPException(status_code=500, detail=str(e))
