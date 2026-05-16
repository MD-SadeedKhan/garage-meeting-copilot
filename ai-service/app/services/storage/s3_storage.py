"""
Garage Meeting Copilot — S3 Artifact Storage
Async S3 client for recordings, exports, and meeting artifacts.
"""
from __future__ import annotations

import io
import json
from datetime import datetime
from typing import Any

import aioboto3
from botocore.exceptions import ClientError

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class S3ArtifactStorage:
    """
    Manages storage and retrieval of meeting artifacts in AWS S3.
    Organises by org/meeting/session hierarchy.
    """

    def __init__(self) -> None:
        self._settings = get_settings()
        self._session = aioboto3.Session(
            aws_access_key_id=self._settings.aws_access_key_id,
            aws_secret_access_key=self._settings.aws_secret_access_key,
            region_name=self._settings.aws_region,
        )

    def _artifact_key(
        self,
        organization_id: str,
        garage_meeting_id: str,
        session_id: str,
        filename: str,
    ) -> str:
        date_prefix = datetime.utcnow().strftime("%Y/%m/%d")
        return (
            f"artifacts/{date_prefix}/{organization_id}/"
            f"{garage_meeting_id}/{session_id}/{filename}"
        )

    def _recording_key(
        self,
        organization_id: str,
        session_id: str,
        filename: str,
    ) -> str:
        date_prefix = datetime.utcnow().strftime("%Y/%m/%d")
        return f"recordings/{date_prefix}/{organization_id}/{session_id}/{filename}"

    async def upload_transcript_export(
        self,
        session_id: str,
        organization_id: str,
        garage_meeting_id: str,
        transcript_text: str,
        format: str = "txt",
    ) -> str:
        """Upload transcript export and return S3 key."""
        filename = f"transcript_{session_id}.{format}"
        key = self._artifact_key(
            organization_id, garage_meeting_id, session_id, filename
        )

        async with self._session.client("s3") as s3:
            await s3.put_object(
                Bucket=self._settings.s3_bucket_artifacts,
                Key=key,
                Body=transcript_text.encode("utf-8"),
                ContentType="text/plain",
                Metadata={
                    "session_id": session_id,
                    "organization_id": organization_id,
                    "garage_meeting_id": garage_meeting_id,
                    "exported_at": datetime.utcnow().isoformat(),
                },
            )

        logger.info("s3_transcript_uploaded", key=key, session_id=session_id)
        return key

    async def upload_summary(
        self,
        session_id: str,
        organization_id: str,
        garage_meeting_id: str,
        summary_content: str,
    ) -> str:
        """Upload meeting summary markdown to S3."""
        filename = f"summary_{session_id}.md"
        key = self._artifact_key(
            organization_id, garage_meeting_id, session_id, filename
        )

        async with self._session.client("s3") as s3:
            await s3.put_object(
                Bucket=self._settings.s3_bucket_artifacts,
                Key=key,
                Body=summary_content.encode("utf-8"),
                ContentType="text/markdown",
            )

        return key

    async def upload_action_items_json(
        self,
        session_id: str,
        organization_id: str,
        garage_meeting_id: str,
        action_items: list[dict[str, Any]],
    ) -> str:
        """Upload action items JSON to S3."""
        filename = f"action_items_{session_id}.json"
        key = self._artifact_key(
            organization_id, garage_meeting_id, session_id, filename
        )

        async with self._session.client("s3") as s3:
            await s3.put_object(
                Bucket=self._settings.s3_bucket_artifacts,
                Key=key,
                Body=json.dumps(
                    {"session_id": session_id, "items": action_items},
                    indent=2,
                ).encode("utf-8"),
                ContentType="application/json",
            )

        return key

    async def upload_screenshot(
        self,
        session_id: str,
        organization_id: str,
        garage_meeting_id: str,
        image_bytes: bytes,
        timestamp: float,
    ) -> str:
        """Upload OCR screenshot to S3."""
        filename = f"screen_{int(timestamp)}.png"
        key = self._artifact_key(
            organization_id, garage_meeting_id, session_id, filename
        )

        async with self._session.client("s3") as s3:
            await s3.put_object(
                Bucket=self._settings.s3_bucket_artifacts,
                Key=key,
                Body=image_bytes,
                ContentType="image/png",
            )

        return key

    async def generate_presigned_url(
        self,
        bucket: str,
        key: str,
        expiry_seconds: int = 3600,
    ) -> str:
        """Generate a pre-signed URL for temporary file access."""
        async with self._session.client("s3") as s3:
            url = await s3.generate_presigned_url(
                ClientMethod="get_object",
                Params={"Bucket": bucket, "Key": key},
                ExpiresIn=expiry_seconds,
            )
        return url

    async def check_connection(self) -> bool:
        """Verify S3 connectivity."""
        try:
            async with self._session.client("s3") as s3:
                await s3.head_bucket(Bucket=self._settings.s3_bucket_artifacts)
            return True
        except Exception as e:
            logger.error("s3_health_check_failed", error=str(e))
            return False


# Module-level singleton
s3_storage = S3ArtifactStorage()
