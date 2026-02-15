"""
他人memoryAPIroute

提供user画像（他人memory）的query、update、delete等function
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import logging

from ...memory.other_memory import OtherMemory, OtherProfile
from ...utils.runtime import get_runtime_paths

logger = logging.getLogger(__name__)

others_router = APIRouter()

# global他人memoryInstance
_other_memory: Optional[OtherMemory] = None


def get_other_memory() -> OtherMemory:
    """get他人memoryInstance"""
    global _other_memory
    if _other_memory is None:
        runtime_paths = get_runtime_paths()
        _other_memory = OtherMemory(str(runtime_paths.others_dir))
    return _other_memory


# ============ data Models ============

class UserProfileResponse(BaseModel):
    """user画像response"""
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None


class UserProfileListResponse(BaseModel):
    """user画像listresponse"""
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None


# ============ API Endpoints ============

@others_router.get("/list", response_model=UserProfileListResponse)
async def list_profiles():
    """
    column出alluser画像

    Returns:
        user画像list
    """
    try:
        other_memory = get_other_memory()
        profiles = other_memory.list_profiles()

        profiles_data = [p.to_dict() for p in profiles]

        return UserProfileListResponse(
            success=True,
            message=f"Found {len(profiles)} 个user画像",
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
    getuser画像

    Args:
        user_id: userid

    Returns:
        user画像
    """
    try:
        other_memory = get_other_memory()
        profile = other_memory.get_profile(user_id)

        if profile is None:
            return UserProfileResponse(
                success=False,
                message=f"user {user_id} 的画像notttt found",
                data=None
            )

        return UserProfileResponse(
            success=True,
            message="getsuccess",
            data=profile.to_dict()
        )
    except Exception as e:
        logger.error(f"Failed to get profile: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@others_router.post("/{user_id}", response_model=UserProfileResponse)
async def update_profile(user_id: str, profile_data: Dict[str, Any]):
    """
    updateuser画像

    Args:
        user_id: userid
        profile_data: 画像data

    Returns:
        updateResult
    """
    try:
        other_memory = get_other_memory()
        profile = other_memory.get_profile(user_id)

        if profile is None:
            # createnew画像
            profile = OtherProfile(user_id=user_id, **profile_data)
        else:
            # update现有画像
            profile_data["user_id"] = user_id
            profile = OtherProfile.from_dict({**profile.to_dict(), **profile_data})

        success = other_memory.save_profile(profile)

        if success:
            return UserProfileResponse(
                success=True,
                message="user画像已save",
                data=profile.to_dict()
            )
        else:
            raise HTTPException(status_code=500, detail="Save failed")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update profile: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@others_router.delete("/{user_id}", response_model=UserProfileResponse)
async def delete_profile(user_id: str):
    """
    deleteuser画像

    Args:
        user_id: userid

    Returns:
        Deletion result
    """
    try:
        other_memory = get_other_memory()
        success = other_memory.delete_profile(user_id)

        if success:
            return UserProfileResponse(
                success=True,
                message=f"user {user_id} 的画像deleted",
                data=None
            )
        else:
            raise HTTPException(status_code=500, detail="deletefailure")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete profile: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@others_router.post("/{user_id}/interaction", response_model=UserProfileResponse)
async def record_interaction(user_id: str, interaction: Dict[str, Any]):
    """
    record交互并updateuser画像

    Args:
        user_id: userid
        interaction: 交互data
            - interaction_type: 交互type
            - outcome: Result（positive/negative/neutral）
            - nottttes: notttte

    Returns:
        update后的画像
    """
    try:
        other_memory = get_other_memory()

        profile = other_memory.update_interaction(
            user_id=user_id,
            interaction_type=interaction.get("interaction_type", "chat"),
            outcome=interaction.get("outcome", "neutral"),
            nottttes=interaction.get("nottttes", ""),
        )

        return UserProfileResponse(
            success=True,
            message="交互已record",
            data=profile.to_dict()
        )
    except Exception as e:
        logger.error(f"Failed to record interaction: {e}")
        raise HTTPException(status_code=500, detail=str(e))
