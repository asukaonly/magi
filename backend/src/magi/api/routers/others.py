"""
Other Person Memory API Routes

Provides query, update, delete and other functions for user profiles (other person memory).
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import logging

from ...personality.other_memory import OtherProfile
from ..services import require_other_memory

logger = logging.getLogger(__name__)

others_router = APIRouter()


# ============ Data Models ============

class UserProfileResponse(BaseModel):
    """User profile response"""
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None


class UserProfileListResponse(BaseModel):
    """User profile list response"""
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None


# ============ API Endpoints ============

@others_router.get("/list", response_model=UserProfileListResponse)
async def list_profiles():
    """
    List all user profiles

    Returns:
        User profile list
    """
    try:
        other_memory = require_other_memory()
        profiles = other_memory.list_profiles()

        profiles_data = [p.to_dict() for p in profiles]

        return UserProfileListResponse(
            success=True,
            message=f"Found {len(profiles)} user profiles",
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
    Get user profile

    Args:
        user_id: User ID

    Returns:
        User profile
    """
    try:
        other_memory = require_other_memory()
        profile = other_memory.get_profile(user_id)

        if profile is None:
            return UserProfileResponse(
                success=False,
                message=f"Profile for user {user_id} not found",
                data=None
            )

        return UserProfileResponse(
            success=True,
            message="Retrieved successfully",
            data=profile.to_dict()
        )
    except Exception as e:
        logger.error(f"Failed to get profile: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@others_router.post("/{user_id}", response_model=UserProfileResponse)
async def update_profile(user_id: str, profile_data: Dict[str, Any]):
    """
    Update user profile

    Args:
        user_id: User ID
        profile_data: Profile data

    Returns:
        Update result
    """
    try:
        other_memory = require_other_memory()
        profile = other_memory.get_profile(user_id)

        if profile is None:
            # Create new profile
            profile = OtherProfile(user_id=user_id, **profile_data)
        else:
            # Update existing profile
            profile_data["user_id"] = user_id
            profile = OtherProfile.from_dict({**profile.to_dict(), **profile_data})

        success = other_memory.save_profile(profile)

        if success:
            return UserProfileResponse(
                success=True,
                message="User profile saved",
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
    Delete user profile

    Args:
        user_id: User ID

    Returns:
        Deletion result
    """
    try:
        other_memory = require_other_memory()
        success = other_memory.delete_profile(user_id)

        if success:
            return UserProfileResponse(
                success=True,
                message=f"Profile for user {user_id} deleted",
                data=None
            )
        else:
            raise HTTPException(status_code=500, detail="Delete failed")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete profile: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@others_router.post("/{user_id}/interaction", response_model=UserProfileResponse)
async def record_interaction(user_id: str, interaction: Dict[str, Any]):
    """
    Record interaction and update user profile

    Args:
        user_id: User ID
        interaction: Interaction data
            - interaction_type: Interaction type
            - outcome: Outcome (positive/negative/neutral)
            - notes: Notes

    Returns:
        Updated profile
    """
    try:
        other_memory = require_other_memory()

        profile = other_memory.update_interaction(
            user_id=user_id,
            interaction_type=interaction.get("interaction_type", "chat"),
            outcome=interaction.get("outcome", "neutral"),
            notes=interaction.get("notes", ""),
        )

        return UserProfileResponse(
            success=True,
            message="Interaction recorded",
            data=profile.to_dict()
        )
    except Exception as e:
        logger.error(f"Failed to record interaction: {e}")
        raise HTTPException(status_code=500, detail=str(e))
