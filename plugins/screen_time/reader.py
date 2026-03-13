"""Screen Time data reader using SQLite database."""
from __future__ import annotations

import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional, List

from .exceptions import PlatformNotSupportedError, DatabaseNotFoundError, DatabaseReadError
from .types import DailyScreenTime, AppUsage


class ScreenTimeReader:
    """Screen Time data reader using SQLite database."""

    def __init__(self) -> None:
        self._db_path: Optional[Path] = None
        self._conn: Optional[sqlite3.Connection] = None
        self._is_available: Optional[bool] = None

    def _find_database(self) -> Path:
        """Find the Screen Time database file.

        Returns:
            Path to the database file

        Raises:
            DatabaseNotFoundError: If database not found
        """
        # Possible database locations
        possible_paths = [
            Path.home() / "Library/Application Support/com.apple.screentime/ScreenTime.db",
        ]

        for path in possible_paths:
            if path.exists():
                return path

        raise DatabaseNotFoundError(
            "Screen Time database not found. Please ensure Screen Time is enabled in System Preferences."
        )

    def is_available(self) -> bool:
        """Check if Screen Time database is available.

        Returns:
            True if available, False otherwise
        """
        if self._is_available is not None:
            return self._is_available

        # Not available on non-darwin platforms
        if sys.platform != "darwin":
            self._is_available = False
            return False

        try:
            db_path = self._find_database()
            self._db_path = db_path
            self._is_available = True
            return True
        except DatabaseNotFoundError:
            self._is_available = False
            return False
        except Exception:
            self._is_available = False
            return False

    @property
    def connection(self) -> sqlite3.Connection:
        """Get or create database connection."""
        if self._conn is None:
            if self._db_path is None:
                self._db_path = self._find_database()
            self._conn = sqlite3.connect(str(self._db_path))
        return self._conn

    def close(self) -> None:
        """Close the database connection if open."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def read_daily_screen_time(
        self,
        start_date: date,
        end_date: date
    ) -> List[DailyScreenTime]:
        """Read daily screen time data from the database.

        Args:
            start_date: Start date for the query
            end_date: End date for the query

        Returns:
            List of DailyScreenTime objects

        Raises:
            DatabaseReadError: If query fails
        """
        if not self.is_available():
            return []

        try:
            conn = self.connection
            cursor = conn.cursor()

            # Convert dates to timestamps for comparison
            start_timestamp = datetime.combine(start_date, datetime.min.time()).timestamp()
            end_timestamp = datetime.combine(end_date, datetime.max.time()).timestamp()

            # Query for daily aggregates - group by date
            # Note: The actual schema may vary by macOS version
            # This is a best-effort implementation
            query = """
                SELECT
                    ZDATE,
                    SUM(ZTOTALTIME) as total_duration
                FROM ZOBJECT
                WHERE ZDATE >= ? AND ZDATE <= ?
                GROUP BY ZDATE
                ORDER BY ZDATE DESC
            """

            cursor.execute(query, (start_timestamp, end_timestamp))
            results = cursor.fetchall()
            cursor.close()

            # Process results into DailyScreenTime objects
            daily_data = []
            for row in results:
                try:
                    entry_date = datetime.fromtimestamp(row[0]).date()
                    total_duration = int(row[1]) if row[1] else 0

                    # Get app usages for this date
                    app_usages = self._get_app_usages_for_date(entry_date)

                    daily = DailyScreenTime(
                        date=entry_date,
                        total_duration=total_duration,
                        app_usages=app_usages
                    )
                    daily_data.append(daily)
                except (ValueError, TypeError, OSError):
                    # Skip invalid entries
                    continue

            return daily_data

        except sqlite3.Error as e:
            raise DatabaseReadError(f"Failed to read Screen Time data: {e}")
        except Exception as e:
            raise DatabaseReadError(f"Unexpected error reading Screen Time data: {e}")

    def _get_app_usages_for_date(self, target_date: date) -> List[AppUsage]:
        """Get app usage breakdown for a specific date.

        Args:
            target_date: The date to query

        Returns:
            List of AppUsage objects
        """
        try:
            conn = self.connection
            cursor = conn.cursor()

            # Convert date to timestamps
            start_timestamp = datetime.combine(target_date, datetime.min.time()).timestamp()
            end_timestamp = datetime.combine(target_date, datetime.max.time()).timestamp()

            # Query app usage for the date
            query = """
                SELECT
                    ZOBJECT as bundle_id,
                    ZTOTALTIME as usage_seconds,
                    ZDOMAIN as category
                FROM ZOBJECT
                WHERE ZDATE >= ? AND ZDATE <= ?
                AND ZOBJECT IS NOT NULL
                ORDER BY ZTOTALTIME DESC
            """

            cursor.execute(query, (start_timestamp, end_timestamp))
            results = cursor.fetchall()
            cursor.close()

            usages = []
            seen_bundles = set()

            for row in results:
                bundle_id = row[0]
                if not bundle_id or bundle_id in seen_bundles:
                    continue
                seen_bundles.add(bundle_id)

                app_name = self._get_app_name(bundle_id)

                # Get usage time - ZTOTALTIME is in seconds
                try:
                    usage_seconds = int(row[1]) if row[1] else 0
                except (ValueError, TypeError):
                    usage_seconds = 0

                # Get category
                category = row[2] if len(row) > 2 and row[2] else None

                if usage_seconds > 0:
                    usages.append(AppUsage(
                        bundle_id=bundle_id,
                        app_name=app_name,
                        usage_seconds=usage_seconds,
                        category=category
                    ))

            return usages

        except sqlite3.Error as e:
            raise DatabaseReadError(f"Failed to read app usage data", query_type="app_details")

    def _get_app_name(self, bundle_id: str) -> str:
        """Get human-readable app name from bundle ID.

        Args:
            bundle_id: Bundle ID (e.g., com.apple.MobileSMS)

        Returns:
            App name string
        """
        # Common bundle ID patterns
        app_names = {
            "com.apple.MobileSMS": "Messages",
            "com.apple.mail": "Mail",
            "com.apple.mobilephone": "Phone",
            "com.apple.Music": "Music",
            "com.apple.Maps": "Maps",
            "com.apple.Safari": "Safari",
            "com.apple.WebKit": "Safari",
            "com.apple.findmy": "Find My",
            "com.apple.preferences": "System Settings",
            "com.apple.AppStore": "App Store",
            "com.apple.Terminal": "Terminal",
            "com.apple.dt": "Xcode",
            "com.apple.Calendar": "Calendar",
            "com.apple.AddressBook": "Contacts",
            "com.apple.Photos": "Photos",
            "com.apple.Preview": "Preview",
            "com.apple.Chat": "Messages",
            "com.apple.FaceTime": "FaceTime",
            "com.apple.Messages": "Messages",
            "com.apple.news": "News",
            "com.apple.stock": "Stocks",
            "com.apple.weather": "Weather",
            "com.apple.ActivityMonitor": "Activity Monitor",
            "com.apple.finder": "Finder",
            "com.apple.dock": "Dock",
            "com.apple.notificationcenterui": "Notification Center",
            "com.apple.Spotlight": "Spotlight",
            # Third-party apps
            "com.google.Chrome": "Chrome",
            "com.google.Chrome.canary": "Chrome Canary",
            "org.mozilla.firefox": "Firefox",
            "com.microsoft.VSCode": "VS Code",
            "com.tinyspeck.slackmacgap": "Slack",
            "com.spotify.client": "Spotify",
            "com.zoom.xos": "Zoom",
            "com.microsoft.teams": "Teams",
            "com.discord": "Discord",
            "com.telegram.desktop": "Telegram",
            "com.whatsapp.desktop": "WhatsApp",
        }

        # Return mapped name or extract from bundle ID
        if bundle_id in app_names:
            return app_names[bundle_id]

        # Try to extract app name from bundle ID
        parts = bundle_id.split(".")
        if len(parts) > 0:
            return parts[-1].replace("-", " ").title()

        return bundle_id
