"""Tests for AppleHealthTimelineSensor."""
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

_plugins_path = Path(__file__).resolve().parents[3] / "plugins"
if str(_plugins_path) not in sys.path:
    sys.path.insert(0, str(_plugins_path))

from apple_health.reader import HealthKitReader
from apple_health.sensor import AppleHealthTimelineSensor
from apple_health.types import HealthDataType, get_default_enabled_types


class TestAppleHealthTimelineSensor:
    """Test cases for AppleHealthTimelineSensor."""

    def test_sensor_properties(self):
        """Test sensor properties are set correctly."""
        sensor = AppleHealthTimelineSensor()

        assert sensor.sensor_id == "timeline.apple_health"
        assert sensor.display_name == "Apple Health"
        assert sensor.source_type == "apple_health"
        assert sensor.polling_mode == "interval"
        assert sensor.default_interval == 60
        assert sensor.update_key_fields == ("data_type", "date", "session_id")
        assert sensor.relation_edge_whitelist == ("TRACKED", "EXERCISED")
        assert sensor.supports_pull_sync is True
        assert sensor.retention_mode == "analyze_only"

    def test_sensor_with_custom_enabled_types(self):
        """Test sensor with custom enabled types."""
        custom_types = [HealthDataType(
            key="steps",
            hk_type="QuantityType",
            display_name="Steps",
            description="Daily step count",
            unit="count",
            aggregation="daily",
            hk_class="HKQuantityTypeIdentifierStepCount",
            edge_types=["steps"]
        )]

        sensor = AppleHealthTimelineSensor(enabled_types=custom_types)
        assert len(sensor.enabled_types) == 1
        assert sensor.enabled_types[0].key == "steps"

    def test_default_enabled_types(self):
        """Test default enabled types are loaded."""
        sensor = AppleHealthTimelineSensor()
        default_types = get_default_enabled_types()

        assert len(sensor.enabled_types) == len(default_types)
        assert [ht.key for ht in sensor.enabled_types] == [ht.key for ht in default_types]

    @patch('apple_health.reader.HealthKitReader')
    def test_reader_property_on_darwin(self, mock_reader_class):
        """Test reader property initialization on macOS."""
        with patch('apple_health.sensor.sys.platform', 'darwin'):
            # Mock the reader
            mock_reader_class.return_value = Mock()

            sensor = AppleHealthTimelineSensor()
            sensor._reader = None

            # Verify accessing the reader doesn't raise an error
            # and returns a mock instance
            reader = sensor.reader
            assert reader is not None

    @patch('apple_health.sensor.HealthKitReader')
    def test_reader_property_non_darwin_raises_error(self, mock_reader_class):
        """Test reader property raises error on non-macOS."""
        with patch('sys.platform', 'linux'):
            sensor = AppleHealthTimelineSensor()

            with pytest.raises(Exception):  # PlatformNotSupportedError
                _ = sensor.reader

    def test_source_item_identity_with_date(self):
        """Test source_item_identity generation with date."""
        sensor = AppleHealthTimelineSensor()
        item = {
            "data_type": "steps",
            "date": "2024-01-01",
            "value": 5000
        }

        identity = sensor.source_item_identity(item)
        assert identity == "apple_health_steps_2024-01-01"

    def test_source_item_identity_with_session_id(self):
        """Test source_item_identity generation with session_id."""
        sensor = AppleHealthTimelineSensor()
        item = {
            "data_type": "sleep",
            "session_id": "session_123",
            "value": 8.5
        }

        identity = sensor.source_item_identity(item)
        assert identity == "apple_health_sleep_session_123"

    def test_source_item_identity_fallback(self):
        """Test source_item_identity generation fallback."""
        sensor = AppleHealthTimelineSensor()
        item = {
            "data_type": "heart_rate",
            "value": 72
        }

        identity = sensor.source_item_identity(item)
        assert identity.startswith("apple_health_heart_rate_")
        assert identity.endswith(str(int(time.time())))

    def test_source_item_version_fingerprint(self):
        """Test source_item_version_fingerprint generation."""
        sensor = AppleHealthTimelineSensor()
        item = {
            "data_type": "steps",
            "date": "2024-01-01",
            "value": 5000
        }

        fingerprint1 = sensor.source_item_version_fingerprint(item)

        # Change value
        item["value"] = 6000
        fingerprint2 = sensor.source_item_version_fingerprint(item)

        # Fingerprints should be different
        assert fingerprint1 != fingerprint2

    @patch('apple_health.reader.HealthKitReader')
    async def test_collect_items(self, mock_reader_class):
        """Test collect_items method."""
        # Setup
        with patch('apple_health.sensor.datetime') as mock_datetime:
            mock_now = datetime(2024, 1, 2, 12, 0, 0)
            mock_datetime.now.return_value = mock_now
            mock_datetime.datetime.datetime = datetime

        reader_instance = Mock(spec=HealthKitReader)
        mock_reader_class.return_value = reader_instance

        # Mock authorization status
        reader_instance.get_authorization_status.return_value = {
            "steps": "sharing_authorized",
            "distance": "sharing_authorized",
            "heart_rate": "sharing_denied"
        }

        # Mock data reading
        reader_instance.read_daily_aggregate.side_effect = [
            [{"data_type": "steps", "date": "2024-01-01", "value": 5000}],
            [{"data_type": "distance", "date": "2024-01-01", "value": 5.2}]
        ]

        with patch('sys.platform', 'darwin'):
            sensor = AppleHealthTimelineSensor()
            sensor._reader = reader_instance

            # Mock context
            from magi.awareness.sensor_sync import SensorSyncContext
            from magi.utils.runtime import RuntimePaths
            context = SensorSyncContext(
            source_type="apple_health",
            manual=False,
            last_cursor=None,
            last_success_at=0,
            limit=100,
            runtime_paths=RuntimePaths(None),
            plugin_settings={}
            )

            # Call collect_items
            result = await sensor.collect_items(context)

            # Verify results
            assert len(result.items) == 2
            assert result.next_cursor is not None
            assert result.watermark_ts > 0

            # Verify reader was called correctly
            assert reader_instance.get_authorization_status.called
            assert reader_instance.read_daily_aggregate.call_count == 2

    @patch('apple_health.sensor.NORMALIZERS')
    async def test_build_output_with_normalizer(self, mock_normalizers):
        """Test build_output with normalizer."""
        # Setup mock normalizer that mimics real normalizer
        def mock_normalizer(item, sensor):
            return {
                "event_id": "test_event",
                "source_item_id": "test_item",
                "occurred_at": 1000,
                "title": "Test Event",
                "summary": "Test Summary",
                "content_blocks": [{"kind": "text", "value": "test"}],
                "tags": ["test"],
                "provenance": {"sensor_id": "test"}
            }

        mock_normalizers.get.return_value = mock_normalizer

        sensor = AppleHealthTimelineSensor()
        item = {
            "data_type": "steps",
            "date": "2024-01-01",
            "value": 5000
        }

        output = await sensor.build_output(item)

        assert output.source_item_id == "test_item"
        assert output.source_type == "apple_health"
        assert output.title == "Test Event"
        assert output.summary == "Test Summary"
        assert len(output.content_blocks) == 1

    @patch('apple_health.sensor.NORMALIZERS')
    async def test_build_output_without_normalizer(self, mock_normalizers):
        """Test build_output without normalizer (fallback)."""
        mock_normalizers.get.return_value = None

        sensor = AppleHealthTimelineSensor()
        item = {
            "data_type": "unknown_type",
            "date": "2024-01-01",
            "timestamp": 1000,
            "occurred_at": 1000,
            "value": 5000
        }

        item["occurred_at"] = 1000
        output = await sensor.build_output(item)

        assert output.source_type == "apple_health"
        assert output.title == "Health Data: Unknown Type"
        assert output.summary == "5000"
        assert "apple_health" in output.tags
        assert "unknown_type" in output.tags

    @patch('apple_health.reader.HealthKitReader')
    @patch('apple_health.sensor.sys.platform', 'darwin')
    async def test_collect_items_with_settings(self, mock_reader_class):
        """Test collect_items respects plugin settings."""
        reader_instance = Mock(spec=HealthKitReader)
        mock_reader_class.return_value = reader_instance

        reader_instance.get_authorization_status.return_value = {
            "steps": "sharing_authorized",
            "distance": "sharing_authorized"
        }

        reader_instance.read_daily_aggregate.return_value = [
            {"data_type": "steps", "date": "2024-01-01", "value": 5000}
        ]

        sensor = AppleHealthTimelineSensor()
        sensor._reader = reader_instance

        # Mock context with settings
        from magi.awareness.sensor_sync import SensorSyncContext
        from magi.utils.runtime import RuntimePaths
        context = SensorSyncContext(
            source_type="apple_health",
            manual=False,
            last_cursor=None,
            last_success_at=0,
            limit=100,
            runtime_paths=RuntimePaths(None),
            plugin_settings={
                "sensors": {
                    "apple_health": {
                        "enabled_types": ["steps"]  # Only enable steps
                    }
                }
            }
        )

        # Call collect_items
        await sensor.collect_items(context)

        # Verify only steps was collected
        assert reader_instance.read_daily_aggregate.call_count == 1  # Only steps
