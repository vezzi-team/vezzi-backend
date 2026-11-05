import hashlib
from dataclasses import asdict
from datetime import UTC, datetime
from io import BytesIO
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, File, Form, UploadFile
from sqlalchemy import select

from app.api.deps import AdminUser, SessionDep, SettingsDep
from app.catalog_import.publisher import publish_catalog
from app.catalog_import.reader import CatalogFormatError, read_catalog
from app.core.errors import BusinessRuleError
from app.models import CatalogImport
from app.schemas.admin import CatalogImportRead, ImportReportRead
from app.schemas.common import error_responses
from app.services.catalog import count_fresh_offers

router = APIRouter(prefix="/admin", tags=["Администрирование"], responses=error_responses(401, 403))


@router.get("/catalog/imports")
def list_imports(_: AdminUser, session: SessionDep) -> list[CatalogImportRead]:
    """История загрузок каталога, последние первыми."""
    imports = session.scalars(select(CatalogImport).order_by(CatalogImport.id.desc()).limit(50))
    return [CatalogImportRead.model_validate(item) for item in imports]


@router.post("/catalog/imports", responses=error_responses(422))
def import_catalog(
    admin: AdminUser,
    session: SessionDep,
    settings: SettingsDep,
    file: Annotated[UploadFile, File(description="Excel-файл каталога (.xlsx)")],
    shift_timestamps: Annotated[
        bool, Form(description="Сдвинуть время цен к текущему (только для синтетических данных)")
    ] = False,
    is_synthetic: Annotated[bool, Form(description="Пометить данные как демонстрационные")] = False,
) -> ImportReportRead:
    """Загрузить новый каталог и атомарно сделать его активным (D02, N04).

    Некорректные строки отклоняются с указанием причины. Повторная загрузка того же
    файла ничего не меняет и возвращает status = unchanged.
    """
    content = file.file.read(settings.max_upload_size_mb * 1024 * 1024 + 1)
    if len(content) > settings.max_upload_size_mb * 1024 * 1024:
        raise BusinessRuleError(
            f"Файл больше {settings.max_upload_size_mb} МБ", code="file_too_large"
        )
    now = datetime.now(UTC)
    try:
        catalog = read_catalog(BytesIO(content), ZoneInfo(settings.catalog_timezone))
        report = publish_catalog(
            session,
            catalog,
            source_name=file.filename or "upload.xlsx",
            file_sha256=hashlib.sha256(content).hexdigest(),
            now=now,
            imported_by_id=admin.id,
            shift_timestamps=shift_timestamps,
            mark_synthetic=is_synthetic,
        )
    except CatalogFormatError as exc:
        raise BusinessRuleError(str(exc), code="invalid_catalog_file") from exc
    fresh = count_fresh_offers(session, report.import_id, now, settings.offer_max_age_hours)
    return ImportReportRead(**asdict(report), fresh_offers_count=fresh)
