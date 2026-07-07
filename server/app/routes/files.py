"""POST /files (streamed multipart upload) and GET /files/{id}/download (SPEC §5, §10)."""

import logging
from datetime import timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from .. import storage
from ..auth import get_current_user
from ..config import settings
from ..db import get_db
from ..models import File as FileModel
from ..models import User, utcnow
from ..ratelimit import RATE_LIMIT, limiter
from ..schemas import FileInfo

logger = logging.getLogger("selfx.routes.files")

router = APIRouter(tags=["files"])


@router.post("/files", response_model=FileInfo, status_code=status.HTTP_201_CREATED)
@limiter.limit(RATE_LIMIT)
def upload_file(
    request: Request,
    file: UploadFile,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FileInfo:
    # fast reject for honest clients before touching the body
    content_length = request.headers.get("content-length", "")
    if content_length.isdigit() and int(content_length) > settings.max_upload_bytes + 16384:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"file exceeds the {settings.max_upload_mb} MB upload limit",
        )

    orig_name = storage.sanitize_orig_name(file.filename or "file")
    try:
        file_id, stored_path, size, mime = storage.save_upload(file.file, orig_name)
    except storage.UploadTooLarge:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"file exceeds the {settings.max_upload_mb} MB upload limit",
        ) from None
    except storage.EmptyUpload:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="uploaded file is empty"
        ) from None

    logger.info(
        "upload by %s: '%s' (%d bytes, sniffed mime %s) -> %s",
        user.username, orig_name, size, mime, stored_path,
    )

    if settings.clamav_enabled:
        try:
            storage.clamav_scan(storage.file_abs_path(stored_path))
        except storage.VirusFound as exc:
            storage.delete_stored_file(stored_path)
            logger.warning("virus detected in upload from %s: %s", user.username, exc.signature)
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"upload rejected: malware detected ({exc.signature})",
            ) from None
        except Exception:
            storage.delete_stored_file(stored_path)
            logger.exception("clamav scan failed")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="virus scanner unavailable, upload rejected",
            ) from None

    expires_at = None
    if settings.file_retention_hours > 0:
        expires_at = utcnow() + timedelta(hours=settings.file_retention_hours)

    row = FileModel(
        id=file_id,
        user_id=user.id,
        kind="upload",
        orig_name=orig_name,
        stored_path=stored_path,
        size=size,
        mime=mime,
        expires_at=expires_at,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return FileInfo.model_validate(row)


@router.get("/files/{file_id}/download")
def download_file(
    file_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FileResponse:
    row = db.get(FileModel, file_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="file not found")
    if row.user_id != user.id and not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not your file")
    path = storage.file_abs_path(row.stored_path)
    if not path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="file is no longer on disk (it may have expired)",
        )
    return FileResponse(
        path,
        filename=row.orig_name,
        media_type=row.mime or "application/octet-stream",
    )
