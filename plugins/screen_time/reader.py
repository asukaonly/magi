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
        except (DatabaseNotFoundError):
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

        conn = self.connection
        cursor = conn.cursor()

        try:
                # Query for daily aggregates
                query = """
                SELECT
                    ZDATE,
                    ZOBJECT,
                    ZTOTALTIME
                FROM ZOBJECT
                WHERE ZDATE >= ? AND ZDATE <= ?
                ORDER BY ZDATE DESC
                """

                results = []
                for row in cursor.fetchall():
                    results.append(row)

                cursor.close()

                # Process results into DailyScreenTime objects
                daily_data = []
                for row in results:
                    entry_date = date.fromtimestamp(row[0])
                    daily = DailyScreenTime(
                        date=entry_date,
                        total_duration=row[2] if row[6] else 0,
                        app_usages=self._parse_app_usages(row)
                    )
                    daily_data.append(daily)

                return daily_data

        except sqlite3.Error as e:
            raise DatabaseReadError(f"Failed to read Screen Time data: {e}")
        finally:
            if conn:
                conn.close()

    def _parse_app_usages(self, row: sqlite3.Row) -> List[AppUsage]:
        """Parse app usage data from a database row.

        Args:
            row: Database row containing ZOBJECT and ZTOTALTIME

        Returns:
            List of AppUsage objects
        """
        try:
            # Query app details for this date
            query = """
                SELECT ZOBJECT, ZTOTALTIME
                FROM ZOBJECT
                WHERE ZDATE = ? AND ZOBJECT = ?
            ORDER BY ZOBJECT
            """

            app_cursor = self.connection.cursor()
            app_results = app_cursor.fetchall()

            usages = []
            for app_row in app_results:
                bundle_id = app_row[0]
                app_name = self._get_app_name(bundle_id)

                # Get usage time - ZTOTALTIME is in seconds
                try:
                    usage_seconds = int(app_row[5])  # Could be None
                except (ValueError, TypeError):
                    usage_seconds = 0

                # Get category from ZDOMAIN if available
                category = app_row[4] if app_row[4] else None

                usages.append(AppUsage(
                    bundle_id=bundle_id,
                    app_name=app_name,
                    usage_seconds=usage_seconds,
                    category=category
                ))

            app_cursor.close()

            return usages
        except sqlite3.Error as e:
            raise DatabaseReadError(f"Failed to read app usage data", query_type="app_details")

        finally:
            app_cursor.close()

        return usages

    def _get_app_name(self, bundle_id: str) -> str:
        """Get human-readable app name from bundle ID.

        Args:
            bundle_id: Bundle ID (e.g., com.apple.MobileSMS)

        Returns:
            App name string
        """
        # Common bundle ID patterns
        app_names = {
            "com.apple.MobileSMS": "短信",
            "com.apple.mail": "邮件",
            "com.apple.mobilephone": "电话",
            "com.apple.Music": "音乐",
            "com.apple.Maps": "地图",
            "com.apple.Safari": "Safari",
            "com.apple.WebKit": "Safari",
            "com.apple.findmy": "查找",
            "com.apple.preferences": "系统设置",
            "com.apple.AppStore": "App Store",
            "com.apple.Terminal": "终端",
            "com.apple.dt": "终端",
            "com.apple.Calendar": "日历",
            "com.apple.AddressBook": "通讯录",
            "com.apple.Photos": "照片",
            "com.apple.Preview": "预览",
            "com.apple.Chat": "聊天",
            "com.apple.FaceTime": "FaceTime",
            "com.apple.Messages": "信息",
            "com.apple.news": "新闻",
            "com.apple.stock": "股市",
            "com.apple.weather": "天气",
            "com.apple.ActivityMonitor": "活动监视器",
        }

        return app_names.get(bundle_id, bundle_id)
