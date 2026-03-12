"""HealthKit data reader using pyobjc bridge."""
from __future__ import annotations

import sys
from datetime import datetime
from typing import Any, Optional

from plugins.apple_health.exceptions import PlatformNotSupportedError
from plugins.apple_health.types import HEALTH_DATA_TYPES, HealthDataType


class HealthKitReader:
    """HealthKit data reader using pyobjc bridge."""

    def __init__(self) -> None:
        self._health_store: Any = None
        self._is_available: Optional[bool] = None
        self._hk_module: dict[str, Any] | None = None
        self._foundation_module: dict[str, Any] | None = None

    def _ensure_platform(self) -> None:
        """Raise error if not running on macOS/iOS."""
        if sys.platform != "darwin":
            raise PlatformNotSupportedError()

    def _import_frameworks(self) -> None:
        """Import HealthKit frameworks (macOS only) with lazy loading."""
        if self._hk_module is not None:
            return

        try:
            # Import HealthKit framework
            from HealthKit import (
                HKHealthStore,
                HKObjectType,
                HKQuantityType,
                HKCategoryType,
                HKWorkoutType,
                HKWorkout,
                HKSample,
                HKQuantitySample,
                HKCategorySample,
                HKQuery,
                HKStatisticsQuery,
                HKStatisticsCollectionQuery,
                HKSampleQuery,
                HKSampleType,
            )
            from HealthKit import (
                HKAuthorizationStatusNotDetermined,
                HKAuthorizationStatusSharingDenied,
                HKAuthorizationStatusSharingAuthorized,
            )
            from HealthKit import (
                HKQuantityTypeIdentifierStepCount,
                HKQuantityTypeIdentifierDistanceWalkingRunning,
                HKQuantityTypeIdentifierFlightsClimbed,
                HKQuantityTypeIdentifierHeartRate,
                HKQuantityTypeIdentifierActiveEnergyBurned,
                HKCategoryTypeIdentifierSleepAnalysis,
            )

            self._hk_module = {
                "HKHealthStore": HKHealthStore,
                "HKObjectType": HKObjectType,
                "HKQuantityType": HKQuantityType,
                "HKCategoryType": HKCategoryType,
                "HKWorkoutType": HKWorkoutType,
                "HKWorkout": HKWorkout,
                "HKSample": HKSample,
                "HKQuantitySample": HKQuantitySample,
                "HKCategorySample": HKCategorySample,
                "HKQuery": HKQuery,
                "HKStatisticsQuery": HKStatisticsQuery,
                "HKStatisticsCollectionQuery": HKStatisticsCollectionQuery,
                "HKSampleQuery": HKSampleQuery,
                "HKSampleType": HKSampleType,
                "HKAuthorizationStatusNotDetermined": HKAuthorizationStatusNotDetermined,
                "HKAuthorizationStatusSharingDenied": HKAuthorizationStatusSharingDenied,
                "HKAuthorizationStatusSharingAuthorized": HKAuthorizationStatusSharingAuthorized,
                "HKQuantityTypeIdentifierStepCount": HKQuantityTypeIdentifierStepCount,
                "HKQuantityTypeIdentifierDistanceWalkingRunning": HKQuantityTypeIdentifierDistanceWalkingRunning,
                "HKQuantityTypeIdentifierFlightsClimbed": HKQuantityTypeIdentifierFlightsClimbed,
                "HKQuantityTypeIdentifierHeartRate": HKQuantityTypeIdentifierHeartRate,
                "HKQuantityTypeIdentifierActiveEnergyBurned": HKQuantityTypeIdentifierActiveEnergyBurned,
                "HKCategoryTypeIdentifierSleepAnalysis": HKCategoryTypeIdentifierSleepAnalysis,
            }
        except ImportError:
            self._hk_module = {}

        try:
            # Import Foundation framework
            from Foundation import (
                NSDate,
                NSPredicate,
                NSSortDescriptor,
                NSRunLoop,
                NSDateFormatter,
            )

            self._foundation_module = {
                "NSDate": NSDate,
                "NSPredicate": NSPredicate,
                "NSSortDescriptor": NSSortDescriptor,
                "NSRunLoop": NSRunLoop,
                "NSDateFormatter": NSDateFormatter,
            }
        except ImportError:
            self._foundation_module = {}

    @property
    def health_store(self) -> Any:
        """Get or create HKHealthStore instance."""
        if self._health_store is None:
            self._ensure_platform()
            self._import_frameworks()

            if not self._hk_module:
                return None

            HKHealthStore = self._hk_module.get("HKHealthStore")
            if HKHealthStore is None:
                return None

            self._health_store = HKHealthStore.alloc().init()

        return self._health_store

    def is_available(self) -> bool:
        """Check if HealthKit is available on this device."""
        if self._is_available is not None:
            return self._is_available

        # Not available on non-darwin platforms
        if sys.platform != "darwin":
            self._is_available = False
            return False

        try:
            self._import_frameworks()

            if not self._hk_module:
                self._is_available = False
                return False

            HKHealthStore = self._hk_module.get("HKHealthStore")
            if HKHealthStore is None:
                self._is_available = False
                return False

            store = HKHealthStore.alloc().init()
            self._is_available = store.isHealthDataAvailable()
            return self._is_available

        except Exception:
            self._is_available = False
            return False

    def get_authorization_status(self, type_keys: list[str]) -> dict[str, str]:
        """
        Get authorization status for specified data types.

        Args:
            type_keys: List of health data type keys (e.g., ["steps", "heart_rate"])

        Returns:
            Dictionary mapping type keys to authorization status:
            - "not_determined": User hasn't been asked yet
            - "sharing_denied": User denied access
            - "sharing_authorized": User granted access
            - "unavailable": Type not available or error occurred
        """
        if not self.is_available():
            return {key: "unavailable" for key in type_keys}

        result = {}

        for key in type_keys:
            try:
                type_config = HEALTH_DATA_TYPES.get(key)
                if not type_config:
                    result[key] = "unavailable"
                    continue

                hk_type = self._get_hk_type(type_config)
                if hk_type is None:
                    result[key] = "unavailable"
                    continue

                status = self.health_store.authorizationStatusForType_(hk_type)

                # Map authorization status
                if status == self._hk_module.get("HKAuthorizationStatusSharingAuthorized"):
                    result[key] = "sharing_authorized"
                elif status == self._hk_module.get("HKAuthorizationStatusSharingDenied"):
                    result[key] = "sharing_denied"
                elif status == self._hk_module.get("HKAuthorizationStatusNotDetermined"):
                    result[key] = "not_determined"
                else:
                    result[key] = "unavailable"

            except Exception:
                result[key] = "unavailable"

        return result

    def _get_hk_type(self, type_config: HealthDataType) -> Any:
        """Get HKObjectType from type configuration.

        Args:
            type_config: Health data type configuration

        Returns:
            HKObjectType instance or None if not available
        """
        if not self._hk_module:
            return None

        try:
            hk_class = type_config.hk_class
            hk_type = type_config.hk_type

            if hk_type == "QuantityType":
                HKQuantityType = self._hk_module.get("HKQuantityType")
                if HKQuantityType is None:
                    return None
                # Get the constant from the module
                identifier = getattr(self._hk_module, hk_class, hk_class)
                return HKQuantityType.quantityTypeForIdentifier_(identifier)
            elif hk_type == "CategoryType":
                HKCategoryType = self._hk_module.get("HKCategoryType")
                if HKCategoryType is None:
                    return None
                identifier = getattr(self._hk_module, hk_class, hk_class)
                return HKCategoryType.categoryTypeForIdentifier_(identifier)
            elif hk_type == "WorkoutType":
                HKWorkoutType = self._hk_module.get("HKWorkoutType")
                if HKWorkoutType is None:
                    return None
                return HKWorkoutType.workoutType()
            else:
                return None

        except Exception:
            return None

    def request_authorization(self, type_keys: list[str]) -> dict[str, bool]:
        """
        Request authorization for specified data types.

        Note: This is an asynchronous operation in HealthKit. On macOS,
        authorization requests may require user interaction through
        system dialogs.

        Args:
            type_keys: List of health data type keys to request access for

        Returns:
            Dictionary mapping type keys to authorization success status
        """
        if not self.is_available():
            return {key: False for key in type_keys}

        result = {}

        # Collect all types to request
        types_to_read = set()

        for key in type_keys:
            type_config = HEALTH_DATA_TYPES.get(key)
            if not type_config:
                result[key] = False
                continue

            hk_type = self._get_hk_type(type_config)
            if hk_type:
                types_to_read.add(hk_type)
            else:
                result[key] = False

        if not types_to_read:
            return result

        # Request authorization
        try:
            # Use NSSet for the types
            from Foundation import NSSet

            types_set = NSSet.setWithSet_(types_to_read)

            # Authorization is async, but we'll use a sync wrapper
            success = False
            error = None

            def completion_handler(granted, err):
                nonlocal success, error
                success = granted
                error = err

            self.health_store.requestAuthorizationToShareTypes_readTypes_completion_(
                None,  # No write types
                types_set,
                completion_handler
            )

            # For sync operation, we'd need to run the runloop
            # This is a simplified stub implementation
            # In a real implementation, you'd need to handle async properly

            for key in type_keys:
                if key not in result:
                    result[key] = success

        except Exception:
            for key in type_keys:
                if key not in result:
                    result[key] = False

        return result

    # Stub methods for data reading (will be implemented later)

    def read_daily_aggregate(
        self,
        type_key: str,
        start_date: datetime,
        end_date: datetime
    ) -> list[dict]:
        """
        Read daily aggregate data for a health type.

        Args:
            type_key: Health data type key (e.g., "steps", "distance")
            start_date: Start date for the query
            end_date: End date for the query

        Returns:
            List of daily aggregate records (stub - returns empty list)

        Note: This is a stub method. Full implementation will be added later.
        """
        if not self.is_available():
            return []

        # Stub implementation - will be completed in a future task
        return []

    def read_samples(
        self,
        type_key: str,
        start: datetime,
        end: datetime,
        limit: int = 100
    ) -> list[dict]:
        """
        Read sample data for a health type.

        Args:
            type_key: Health data type key (e.g., "heart_rate")
            start: Start datetime for the query
            end: End datetime for the query
            limit: Maximum number of samples to return

        Returns:
            List of sample records (stub - returns empty list)

        Note: This is a stub method. Full implementation will be added later.
        """
        if not self.is_available():
            return []

        # Stub implementation - will be completed in a future task
        return []

    def read_sessions(
        self,
        type_key: str,
        start: datetime,
        end: datetime
    ) -> list[dict]:
        """
        Read session data for a health type (e.g., sleep sessions).

        Args:
            type_key: Health data type key (e.g., "sleep")
            start: Start datetime for the query
            end: End datetime for the query

        Returns:
            List of session records (stub - returns empty list)

        Note: This is a stub method. Full implementation will be added later.
        """
        if not self.is_available():
            return []

        # Stub implementation - will be completed in a future task
        return []

    def read_workouts(
        self,
        start: datetime,
        end: datetime
    ) -> list[dict]:
        """
        Read workout data from HealthKit.

        Args:
            start: Start datetime for the query
            end: End datetime for the query

        Returns:
            List of workout records (stub - returns empty list)

        Note: This is a stub method. Full implementation will be added later.
        """
        if not self.is_available():
            return []

        # Stub implementation - will be completed in a future task
        return []
