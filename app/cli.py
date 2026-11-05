"""Команды администратора: `uv run vezzi <команда>`. Список команд: `uv run vezzi --help`."""

import argparse
import getpass
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.catalog_import.publisher import ImportReport, publish_catalog
from app.catalog_import.reader import CatalogFormatError, read_catalog
from app.catalog_import.template import write_template
from app.core.config import get_settings
from app.core.security import hash_password
from app.db.session import get_session_factory
from app.demo.catalog import build_demo_catalog
from app.models import User, UserRole
from app.schemas.auth import PASSWORD_MIN_LENGTH
from app.services.auth import normalize_email
from app.services.catalog import count_fresh_offers


def create_admin(args: argparse.Namespace) -> int:
    email = normalize_email(args.email)
    password = getpass.getpass("Пароль администратора: ")
    if len(password) < PASSWORD_MIN_LENGTH:
        print(f"Пароль должен быть не короче {PASSWORD_MIN_LENGTH} символов", file=sys.stderr)
        return 1
    with get_session_factory()() as session:
        if session.scalar(select(User).where(User.email == email)) is not None:
            print(f"Пользователь {email} уже существует", file=sys.stderr)
            return 1
        session.add(User(email=email, password_hash=hash_password(password), role=UserRole.ADMIN))
        session.commit()
    print(f"Администратор {email} создан")
    return 0


def import_catalog(args: argparse.Namespace) -> int:
    path: Path = args.file
    settings = get_settings()
    now = datetime.now(UTC)
    try:
        catalog = read_catalog(path, ZoneInfo(settings.catalog_timezone))
        with get_session_factory()() as session:
            report = publish_catalog(
                session,
                catalog,
                source_name=path.name,
                file_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                now=now,
                shift_timestamps=args.shift_timestamps,
                mark_synthetic=args.synthetic,
            )
            fresh = count_fresh_offers(session, report.import_id, now, settings.offer_max_age_hours)
    except CatalogFormatError as exc:
        print(f"Каталог не загружен: {exc}", file=sys.stderr)
        return 1
    _print_report(report, show_errors=args.show_errors)
    print(
        f"  участвуют в расчёте сейчас: {fresh} цен из {report.offers_count} "
        f"(в наличии и не старше {settings.offer_max_age_hours} ч)"
    )
    return 0


def seed_demo(_: argparse.Namespace) -> int:
    now = datetime.now(UTC)
    catalog = build_demo_catalog(now)
    with get_session_factory()() as session:
        report = publish_catalog(
            session,
            catalog,
            source_name="demo",
            file_sha256=hashlib.sha256(now.isoformat().encode()).hexdigest(),
            now=now,
        )
    _print_report(report, show_errors=False)
    return 0


def catalog_template(args: argparse.Namespace) -> int:
    write_template(args.output)
    print(f"Шаблон сохранён: {args.output}")
    return 0


def export_openapi(args: argparse.Namespace) -> int:
    from app.main import create_app

    schema = create_app().openapi()
    args.output.write_text(
        json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"OpenAPI сохранён: {args.output}")
    return 0


def _print_report(report: ImportReport, show_errors: bool) -> None:
    if report.status == "unchanged":
        print(f"Этот файл уже загружен (снимок #{report.import_id}), ничего не изменилось")
        return
    print(f"Опубликован снимок каталога #{report.import_id}")
    print(f"  магазинов: {report.stores_count}, товаров: {report.products_count}")
    print(f"  цен: {report.offers_count}, отклонено строк: {report.rejected_rows_count}")
    if report.skipped_weighted_products:
        print(
            f"  пропущено весовых товаров: {report.skipped_weighted_products} "
            f"(их цен: {report.skipped_weighted_offers}), в MVP они не загружаются"
        )
    if report.is_synthetic:
        print("  данные помечены как синтетические")
    if report.timestamps_shifted:
        print("  время цен сдвинуто к текущему моменту")
    if show_errors:
        for error in report.errors:
            print(f"  [{error.sheet}, строка {error.row}] {error.message}")
    elif report.errors:
        print("  причины отказов: добавьте флаг --show-errors")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vezzi", description="Команды backend Vezzi")
    commands = parser.add_subparsers(dest="command", required=True)

    admin = commands.add_parser("create-admin", help="создать администратора")
    admin.add_argument("--email", required=True)
    admin.set_defaults(handler=create_admin)

    importer = commands.add_parser("import-catalog", help="загрузить каталог из Excel")
    importer.add_argument("file", type=Path)
    importer.add_argument(
        "--shift-timestamps",
        action="store_true",
        help="сдвинуть время цен к текущему (только для синтетических данных)",
    )
    importer.add_argument(
        "--synthetic",
        action="store_true",
        help="пометить данные как демонстрационные (приложение покажет это пользователю)",
    )
    importer.add_argument("--show-errors", action="store_true", help="показать отклонённые строки")
    importer.set_defaults(handler=import_catalog)

    demo = commands.add_parser("seed-demo", help="загрузить демонстрационный каталог")
    demo.set_defaults(handler=seed_demo)

    template = commands.add_parser("catalog-template", help="создать Excel-шаблон каталога")
    template.add_argument("output", type=Path)
    template.set_defaults(handler=catalog_template)

    openapi = commands.add_parser("export-openapi", help="сохранить спецификацию OpenAPI в файл")
    openapi.add_argument("output", type=Path)
    openapi.set_defaults(handler=export_openapi)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    sys.exit(args.handler(args))


if __name__ == "__main__":
    main()
