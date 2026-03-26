"""HealthKit data reader using pyobjc bridge."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from typing import Any, Optional

from .exceptions import PlatformNotSupportedError
from .types import HEALTH_DATA_TYPES, HealthDataType


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
                HKUnit,
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
            from HealthKit import HKStatisticsOptionCumulativeSum, HKObjectQueryNoLimit

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
                "HKUnit": HKUnit,
                "HKAuthorizationStatusNotDetermined": HKAuthorizationStatusNotDetermined,
                "HKAuthorizationStatusSharingDenied": HKAuthorizationStatusSharingDenied,
                "HKAuthorizationStatusSharingAuthorized": HKAuthorizationStatusSharingAuthorized,
                "HKStatisticsOptionCumulativeSum": HKStatisticsOptionCumulativeSum,
                "HKObjectQueryNoLimit": HKObjectQueryNoLimit,
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
                NSDateComponents,
            )

            self._foundation_module = {
                "NSDate": NSDate,
                "NSPredicate": NSPredicate,
                "NSSortDescriptor": NSSortDescriptor,
                "NSRunLoop": NSRunLoop,
                "NSDateFormatter": NSDateFormatter,
                "NSDateComponents": NSDateComponents,
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
                identifier = self._hk_module.get(hk_class, hk_class)
                return HKQuantityType.quantityTypeForIdentifier_(identifier)
            elif hk_type == "CategoryType":
                HKCategoryType = self._hk_module.get("HKCategoryType")
                if HKCategoryType is None:
                    return None
                identifier = self._hk_module.get(hk_class, hk_class)
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

    def _call_selector(self, target: Any, selector_names: list[str], *args: Any) -> Any:
        """Call the first available Objective-C selector."""
        for selector_name in selector_names:
            method = getattr(target, selector_name, None)
            if callable(method):
                return method(*args)
        raise AttributeError(f"Unable to find selector on {target!r}: {selector_names}")

    def _to_nsdate(self, value: datetime) -> Any:
        """Convert a Python datetime to NSDate."""
        NSDate = (self._foundation_module or {}).get("NSDate")
        if NSDate is None:
            return None
        return self._call_selector(NSDate, ["dateWithTimeIntervalSince1970_"], float(value.timestamp()))

    def _to_datetime(self, value: Any) -> datetime | None:
        """Convert NSDate-like values into Python datetimes."""
        if isinstance(value, datetime):
            return value
        if value is None:
            return None
        timestamp_getter = getattr(value, "timeIntervalSince1970", None)
        if callable(timestamp_getter):
            try:
                return datetime.fromtimestamp(float(timestamp_getter()))
            except Exception:
                return None
        return None

    def _build_sample_predicate(self, start: datetime, end: datetime) -> Any:
        """Build a HealthKit sample predicate."""
        HKQuery = (self._hk_module or {}).get("HKQuery")
        if HKQuery is None:
            return None
        start_date = self._to_nsdate(start)
        end_date = self._to_nsdate(end)
        if start_date is None or end_date is None:
            return None
        return self._call_selector(
            HKQuery,
            [
                "predicateForSamplesWithStartDate_endDate_options_",
                "predicateForSamples_withStartDate_endDate_options_",
            ],
            start_date,
            end_date,
            0,
        )

    def _drain_run_loop(self, completion_flag: dict[str, bool], *, timeout_seconds: float = 5.0) -> bool:
        """Wait for an async HealthKit callback to finish."""
        NSRunLoop = (self._foundation_module or {}).get("NSRunLoop")
        NSDate = (self._foundation_module or {}).get("NSDate")
        if NSRunLoop is None or NSDate is None:
            return False
        run_loop = self._call_selector(NSRunLoop, ["currentRunLoop"])
        deadline = datetime.now().timestamp() + timeout_seconds
        while not completion_flag["done"] and datetime.now().timestamp() < deadline:
            self._call_selector(
                run_loop,
                ["runUntilDate_"],
                self._call_selector(NSDate, ["dateWithTimeIntervalSinceNow_"], 0.05),
            )
        return completion_flag["done"]

    def _get_unit_for_type(self, type_key: str) -> Any:
        """Resolve the correct HKUnit for a quantity type."""
        HKUnit = (self._hk_module or {}).get("HKUnit")
        if HKUnit is None:
            return None
        if type_key in {"steps", "flights"}:
            return self._call_selector(HKUnit, ["countUnit"])
        if type_key == "distance":
            return self._call_selector(HKUnit, ["meterUnit"])
        if type_key == "active_energy":
            return self._call_selector(HKUnit, ["kilocalorieUnit"])
        if type_key == "heart_rate":
            count_unit = self._call_selector(HKUnit, ["countUnit"])
            minute_unit = self._call_selector(HKUnit, ["minuteUnit"])
            return self._call_selector(count_unit, ["unitDividedByUnit_"], minute_unit)
        return None

    def _coerce_quantity_value(self, type_key: str, quantity: Any) -> float | None:
        """Convert HKQuantity values into Python floats."""
        if quantity is None:
            return None
        unit = self._get_unit_for_type(type_key)
        if unit is None:
            return None
        value = float(self._call_selector(quantity, ["doubleValueForUnit_"], unit))
        if type_key == "distance":
            return value / 1000.0
        return value

    def _execute_statistics_collection_query(
        self,
        type_key: str,
        start_date: datetime,
        end_date: datetime,
    ) -> list[dict[str, Any]]:
        """Execute daily cumulative statistics queries."""
        type_config = HEALTH_DATA_TYPES.get(type_key)
        hk_type = self._get_hk_type(type_config) if type_config else None
        HKStatisticsQuery = (self._hk_module or {}).get("HKStatisticsQuery")
        if hk_type is None or HKStatisticsQuery is None:
            return []

        results: list[dict[str, Any]] = []
        current_day = datetime(start_date.year, start_date.month, start_date.day)
        end_boundary = datetime(end_date.year, end_date.month, end_date.day)
        if end_date > end_boundary:
            end_boundary += timedelta(days=1)

        while current_day < end_boundary:
            next_day = current_day + timedelta(days=1)
            predicate = self._build_sample_predicate(current_day, next_day)
            if predicate is None:
                break

            completion_state = {"done": False}
            payload: dict[str, Any] = {"statistics": None, "error": None}

            def completion_handler(_query: Any, statistics: Any, error: Any) -> None:
                payload["statistics"] = statistics
                payload["error"] = error
                completion_state["done"] = True

            query = self._call_selector(
                HKStatisticsQuery.alloc(),
                ["initWithQuantityType_quantitySamplePredicate_options_completionHandler_"],
                hk_type,
                predicate,
                (self._hk_module or {}).get("HKStatisticsOptionCumulativeSum", 0),
                completion_handler,
            )
            self._call_selector(self.health_store, ["executeQuery_"], query)
            if not self._drain_run_loop(completion_state):
                break

            statistics = payload.get("statistics")
            quantity = statistics.sumQuantity() if statistics is not None and hasattr(statistics, "sumQuantity") else None
            value = self._coerce_quantity_value(type_key, quantity)
            if value is not None and value > 0:
                results.append({"date": current_day, "value": value})
            current_day = next_day

        return results

    def _execute_sample_query(
        self,
        type_key: str,
        start: datetime,
        end: datetime,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Execute a HealthKit sample query and return Python-native rows."""
        type_config = HEALTH_DATA_TYPES.get(type_key)
        hk_type = self._get_hk_type(type_config) if type_config else None
        HKSampleQuery = (self._hk_module or {}).get("HKSampleQuery")
        NSSortDescriptor = (self._foundation_module or {}).get("NSSortDescriptor")
        if hk_type is None or HKSampleQuery is None or NSSortDescriptor is None:
            return []

        predicate = self._build_sample_predicate(start, end)
        if predicate is None:
            return []

        completion_state = {"done": False}
        payload: dict[str, Any] = {"samples": None, "error": None}

        def completion_handler(_query: Any, samples: Any, error: Any) -> None:
            payload["samples"] = samples
            payload["error"] = error
            completion_state["done"] = True

        sort_descriptor = self._call_selector(
            NSSortDescriptor,
            ["sortDescriptorWithKey_ascending_"],
            "startDate",
            True,
        )
        query = self._call_selector(
            HKSampleQuery.alloc(),
            ["initWithSampleType_predicate_limit_sortDescriptors_resultsHandler_"],
            hk_type,
            predicate,
            limit if limit > 0 else (self._hk_module or {}).get("HKObjectQueryNoLimit", 0),
            [sort_descriptor],
            completion_handler,
        )
        self._call_selector(self.health_store, ["executeQuery_"], query)
        if not self._drain_run_loop(completion_state):
            return []
        if payload.get("error") is not None:
            return []

        rows: list[dict[str, Any]] = []
        for sample in payload.get("samples") or []:
            start_value = getattr(sample, "startDate", None)
            end_value = getattr(sample, "endDate", None)
            if callable(start_value):
                start_value = start_value()
            if callable(end_value):
                end_value = end_value()
            start_dt = self._to_datetime(start_value)
            end_dt = self._to_datetime(end_value)
            if start_dt is None or end_dt is None:
                continue
            rows.append(
                {
                    "start_date": start_dt,
                    "end_date": end_dt,
                    "sample": sample,
                }
            )
        return rows

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
            from Foundation import NSDate, NSRunLoop, NSSet

            types_set = NSSet.setWithSet_(types_to_read)

            # Authorization is async, but we'll use a sync wrapper
            success = False
            error = None
            completed = False

            def completion_handler(granted, err):
                nonlocal success, error, completed
                success = granted
                error = err
                completed = True

            self.health_store.requestAuthorizationToShareTypes_readTypes_completion_(
                None,  # No write types
                types_set,
                completion_handler
            )

            run_loop = NSRunLoop.currentRunLoop()
            deadline = datetime.now().timestamp() + 5.0
            while not completed and datetime.now().timestamp() < deadline:
                run_loop.runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.05))

            for key in type_keys:
                if key not in result:
                    result[key] = bool(success) and error is None

        except Exception:
            for key in type_keys:
                if key not in result:
                    result[key] = False

        return result

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
            List of daily aggregate records.
        """
        if not self.is_available():
            return []
        type_config = HEALTH_DATA_TYPES.get(type_key)
        if not type_config or type_config.aggregation != "daily":
            return []
        rows = self._execute_statistics_collection_query(type_key, start_date, end_date)
        results: list[dict[str, Any]] = []
        for row in rows:
            row_date = row.get("date")
            row_value = row.get("value")
            if row_date is None or row_value is None:
                continue
            if isinstance(row_date, datetime):
                date_value = row_date.date().isoformat()
            else:
                date_value = str(row_date)
            results.append(
                {
                    "data_type": type_key,
                    "date": date_value,
                    "value": row_value,
                }
            )
        return results

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
            List of session records.
        """
        if not self.is_available():
            return []
        type_config = HEALTH_DATA_TYPES.get(type_key)
        if not type_config or type_config.aggregation != "session":
            return []
        rows = self._execute_sample_query(type_key, start, end, limit=200)
        results: list[dict[str, Any]] = []
        for row in rows:
            start_value = row.get("start_date")
            end_value = row.get("end_date")
            if not isinstance(start_value, datetime) or not isinstance(end_value, datetime):
                continue
            results.append(
                {
                    "data_type": type_key,
                    "start_time": start_value.timestamp(),
                    "end_time": end_value.timestamp(),
                    "session_id": (
                        f"{type_key}_{start_value.strftime('%Y%m%d%H%M%S')}_"
                        f"{end_value.strftime('%Y%m%d%H%M%S')}"
                    ),
                }
            )
        return results

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
