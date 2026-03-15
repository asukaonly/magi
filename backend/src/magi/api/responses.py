"""
Unified response format.

Defines standard API response shapes.
"""
from typing import Any, Optional, List
from pydantic import BaseModel, Field


class SuccessResponse(BaseModel):
    """Success response."""

    success: bool = True
    message: str = "operation successful"
    data: Optional[Any] = None

    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "message": "operation successful",
                "data": {"id": 1, "name": "example"},
            }
        }


class ErrorResponse(BaseModel):
    """Error response."""

    success: bool = False
    message: str
    error_code: Optional[str] = None
    details: Optional[Any] = None

    class Config:
        json_schema_extra = {
            "example": {
                "success": False,
                "message": "An error occurred",
                "error_code": "internal_error",
                "details": {},
            }
        }


class PaginatedResponse(BaseModel):
    """Paginated response."""

    success: bool = True
    data: List[Any] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 10
    total_pages: int = 0

    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "data": [{"id": 1}, {"id": 2}],
                "total": 100,
                "page": 1,
                "page_size": 10,
                "total_pages": 10,
            }
        }


def success(data: Any = None, message: str = "operation successful") -> dict:
    """Build a success response dict."""
    return {
        "success": True,
        "message": message,
        "data": data,
    }


def error(message: str, error_code: str = None, details: Any = None) -> dict:
    """Build an error response dict."""
    response = {
        "success": False,
        "message": message,
    }
    if error_code:
        response["error_code"] = error_code
    if details is not None:
        response["details"] = details
    return response


def paginated(
    data: List[Any],
    total: int,
    page: int = 1,
    page_size: int = 10,
) -> dict:
    """Build a paginated response dict."""
    total_pages = (total + page_size - 1) // page_size
    return {
        "success": True,
        "data": data,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }
