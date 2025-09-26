"""
Minimal activity reporter shim used by the Telegram webhook to log user activity.

This vendor module provides a simple `create_reporter` factory that returns an
object with a `report_activity(user_id)` method. It writes documents to MongoDB
using the provided connection string. Failures are logged and never raise.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional

import structlog

try:
    from pymongo import MongoClient
    from pymongo.collection import Collection
    from pymongo.errors import PyMongoError
except Exception:  # pragma: no cover
    # Lazy import errors handled later in runtime calls
    MongoClient = None  # type: ignore
    Collection = None  # type: ignore
    PyMongoError = Exception  # type: ignore


logger = structlog.get_logger(__name__)


class _ActivityReporter:
    def __init__(self, mongodb_uri: str, service_id: str, service_name: str) -> None:
        self._mongodb_uri = mongodb_uri
        self._service_id = service_id
        self._service_name = service_name
        self._collection: Optional[Collection] = None

    def _ensure_connection(self) -> None:
        if self._collection is not None:
            return
        if MongoClient is None:  # pymongo not installed
            raise RuntimeError("pymongo is not installed")

        db_name = os.getenv("ACTIVITY_REPORTER_DB_NAME", "activity")
        collection_name = os.getenv("ACTIVITY_REPORTER_COLLECTION", "user_activity")

        client = MongoClient(self._mongodb_uri, serverSelectionTimeoutMS=2000)
        db = client.get_database(db_name)
        self._collection = db.get_collection(collection_name)

    def report_activity(self, user_id: int | str | None) -> None:
        if not user_id:
            return
        try:
            self._ensure_connection()
            if not self._collection:
                return
            doc = {
                "user_id": str(user_id),
                "service_id": self._service_id,
                "service_name": self._service_name,
                "timestamp": datetime.now(timezone.utc),
            }
            self._collection.insert_one(doc)
        except PyMongoError as e:  # type: ignore
            logger.warning("activity_reporter.mongo_error", error=str(e))
        except Exception as e:  # pragma: no cover
            logger.warning("activity_reporter.error", error=str(e))


def create_reporter(*, mongodb_uri: str, service_id: str, service_name: str) -> _ActivityReporter:
    return _ActivityReporter(mongodb_uri=mongodb_uri, service_id=service_id, service_name=service_name)

