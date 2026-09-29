"""Локальный вход: регистрация, проверка пароля, блокировка перебора (ADR-0031).

Пароль хранится только хешем argon2id в `local_credentials`. Хеширование — нагрузка на
процессор в десятки миллисекунд, поэтому оно уходит в поток: иначе каждая попытка входа
останавливала бы цикл событий API для всех остальных запросов.

Счётчик неудач живёт в базе, а не в памяти процесса: перезапуск API не обнуляет перебор.
Проверок прав здесь нет — сервис вызывают граница HTTP и команда обслуживания.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import cache
from typing import Final

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import sessions
from app.core.workspace import DEV_WORKSPACE_ID
from app.domain import ApprovalStatus, Role, UserKind
from app.errors import DomainError, ErrorCode
from app.models import LocalCredential, UserIdentity
from app.services import identity as identity_service
from app.services import users as users_service

# Издатель локальных личностей. Субъект — почта в нижнем регистре: уникальность пары
# (издатель, субъект) и есть уникальность адреса среди локальных учётных записей.
LOCAL_ISSUER: Final = "local"

MIN_PASSWORD_LENGTH: Final = 10

# Пять промахов подряд — пауза на четверть часа. Живой человек, забывший пароль, успевает
# попробовать все свои варианты; перебор по словарю превращается в годы.
MAX_FAILED_ATTEMPTS: Final = 5
LOCKOUT: Final = timedelta(minutes=15)

# Минимальный профиль OWASP для argon2id: 19 МиБ памяти, два прохода, один поток. Профиль
# библиотеки по умолчанию берёт 64 МиБ на попытку — на сервере с четырьмя гигабайтами и
# лимитом контейнера в полгигабайта это слишком дорого для одновременных входов.
_HASHER: Final = PasswordHasher(time_cost=2, memory_cost=19 * 1024, parallelism=1)


@dataclass(frozen=True, slots=True)
class LoginOutcome:
    """Итог попытки входа.

    Отказ возвращается значением, а не исключением: счётчик неудач обязан попасть в базу,
    а исключение откатило бы транзакцию вместе с ним. Фиксирует её вызывающий.
    """

    user: UserIdentity | None
    credential: LocalCredential | None
    error: ErrorCode | None


def normalize_email(raw: str) -> str:
    """Адрес как ключ: без пробелов по краям и в нижнем регистре."""
    return raw.strip().lower()


def check_password_policy(password: str) -> None:
    """Минимальные требования к паролю.

    Длина важнее «сложности»: фраза из нескольких слов стойче короткого пароля со всеми
    классами символов. Отсекается только то, что заведомо подбирается.
    """
    if len(password) < MIN_PASSWORD_LENGTH:
        raise DomainError(
            ErrorCode.CREDENTIAL_TOO_WEAK,
            f"Пароль должен быть не короче {MIN_PASSWORD_LENGTH} символов",
        )
    if len(set(password)) < 4:
        raise DomainError(ErrorCode.CREDENTIAL_TOO_WEAK, "Пароль из повторяющихся символов")


async def hash_password(password: str) -> str:
    return await asyncio.to_thread(_HASHER.hash, password)


def _verify_sync(password_hash: str, password: str) -> bool:
    try:
        return _HASHER.verify(password_hash, password)
    except VerifyMismatchError:
        return False
    except (VerificationError, InvalidHashError):
        # Повреждённый хеш — не повод пускать и не повод ронять вход пятисоткой.
        return False


async def verify_password(password_hash: str, password: str) -> bool:
    return await asyncio.to_thread(_verify_sync, password_hash, password)


@cache
def _dummy_hash() -> str:
    """Хеш-пустышка для отказа по неизвестному адресу.

    Без него ответ на неизвестную почту приходил бы заметно быстрее, чем на известную с
    неверным паролем, и по времени ответа читался бы список пользователей портала.
    """
    return _HASHER.hash("quantor-timing-equalizer")


def sign_in_error(user: UserIdentity) -> ErrorCode | None:
    """Почему личность с верным паролем всё равно не входит."""
    if not user.is_active:
        return ErrorCode.ACCOUNT_DISABLED
    if user.approval_status is ApprovalStatus.PENDING:
        return ErrorCode.ACCOUNT_PENDING
    if user.approval_status is ApprovalStatus.REJECTED:
        return ErrorCode.ACCOUNT_REJECTED
    return None


async def register(
    session: AsyncSession, *, email: str, display_name: str, password: str
) -> UserIdentity | None:
    """Заводит заявку на доступ. None — адрес уже занят.

    Хеш считается до поиска адреса: иначе занятый адрес отвечал бы быстрее свободного.
    """
    check_password_policy(password)
    password_hash = await hash_password(password)
    subject = normalize_email(email)

    existing = await identity_service.get_user_by_subject(
        session, issuer=LOCAL_ISSUER, subject=subject
    )
    if existing is not None:
        return None

    user = UserIdentity(
        issuer=LOCAL_ISSUER,
        subject=subject,
        email=subject,
        email_verified=False,
        display_name=display_name.strip() or None,
        kind=UserKind.HUMAN,
        approval_status=ApprovalStatus.PENDING,
    )
    try:
        # Точка сохранения: одновременная регистрация того же адреса упирается в
        # уникальность (издатель, субъект) и должна дать тот же ответ «заявка принята».
        async with session.begin_nested():
            session.add(user)
            await session.flush()
            session.add(LocalCredential(user_id=user.id, password_hash=password_hash))
            await session.flush()
    except IntegrityError:
        return None
    return user


async def authenticate(
    session: AsyncSession, *, email: str, password: str, now: datetime | None = None
) -> LoginOutcome:
    """Проверяет пароль и допуск.

    Порядок важен: состояние заявки сообщается только тому, кто знает пароль. Иначе
    форма входа рассказывала бы любому, чья заявка ждёт одобрения, а чья отклонена.
    """
    moment = now or datetime.now(UTC)
    user = await identity_service.get_user_by_subject(
        session, issuer=LOCAL_ISSUER, subject=normalize_email(email)
    )
    credential = await session.get(LocalCredential, user.id) if user is not None else None
    if user is None or credential is None:
        await verify_password(_dummy_hash(), password)
        return LoginOutcome(user=None, credential=None, error=ErrorCode.CREDENTIAL_INVALID)

    if credential.locked_until is not None and credential.locked_until > moment:
        return LoginOutcome(user=user, credential=credential, error=ErrorCode.TOO_MANY_ATTEMPTS)

    if not await verify_password(credential.password_hash, password):
        credential.failed_attempts += 1
        if credential.failed_attempts >= MAX_FAILED_ATTEMPTS:
            credential.locked_until = moment + LOCKOUT
            credential.failed_attempts = 0
        return LoginOutcome(user=user, credential=credential, error=ErrorCode.CREDENTIAL_INVALID)

    credential.failed_attempts = 0
    credential.locked_until = None
    # Параметры хеша могли смениться с прошлого входа: пересчитываем, пока пароль в руках.
    if _HASHER.check_needs_rehash(credential.password_hash):
        credential.password_hash = await hash_password(password)

    error = sign_in_error(user)
    if error is not None:
        return LoginOutcome(user=user, credential=credential, error=error)

    user.last_login_at = moment
    return LoginOutcome(user=user, credential=credential, error=None)


async def change_password(
    session: AsyncSession, *, user_id: uuid.UUID, current: str, new: str
) -> None:
    """Смена собственного пароля с проверкой текущего."""
    credential = await session.get(LocalCredential, user_id)
    if credential is None:
        raise DomainError(ErrorCode.USER_STATE_INVALID, "У учётной записи нет пароля портала")
    if not await verify_password(credential.password_hash, current):
        raise DomainError(ErrorCode.CREDENTIAL_INVALID, "Текущий пароль неверен")
    check_password_policy(new)
    if new == current:
        raise DomainError(ErrorCode.CREDENTIAL_TOO_WEAK, "Новый пароль совпадает с текущим")

    credential.password_hash = await hash_password(new)
    credential.must_change_password = False
    credential.failed_attempts = 0
    credential.locked_until = None
    await session.flush()


async def set_password_by_admin(
    session: AsyncSession, *, user: UserIdentity, password: str
) -> None:
    """Временный пароль от администратора.

    Пароль знают двое, поэтому пользователь обязан сменить его при входе, а все его
    действующие сеансы гаснут: выданный пароль заменяет прежний, а не добавляется к нему.
    """
    if user.issuer != LOCAL_ISSUER:
        raise DomainError(
            ErrorCode.USER_STATE_INVALID, "Пользователь входит через внешний провайдер"
        )
    check_password_policy(password)
    password_hash = await hash_password(password)

    credential = await session.get(LocalCredential, user.id)
    if credential is None:
        credential = LocalCredential(user_id=user.id, password_hash=password_hash)
        session.add(credential)
    else:
        credential.password_hash = password_hash
    credential.must_change_password = True
    credential.failed_attempts = 0
    credential.locked_until = None
    await sessions.revoke_all_for_user(session, user.id)
    await session.flush()


async def create_platform_admin(
    session: AsyncSession, *, email: str, password: str, display_name: str | None
) -> UserIdentity:
    """Администратор платформы из командной строки сервера.

    Команда, а не подсказка в окружении: у локального входа нет провайдера, который
    удостоверил бы почту, и первый зарегистрировавшийся с «нужным» адресом не должен
    становиться администратором. Повторный вызов — это восстановление доступа: пароль
    меняется, права и одобрение возвращаются.
    """
    check_password_policy(password)
    password_hash = await hash_password(password)
    subject = normalize_email(email)

    user = await identity_service.get_user_by_subject(session, issuer=LOCAL_ISSUER, subject=subject)
    if user is None:
        user = UserIdentity(
            issuer=LOCAL_ISSUER,
            subject=subject,
            email=subject,
            email_verified=False,
            display_name=(display_name or "").strip() or None,
            kind=UserKind.HUMAN,
        )
        session.add(user)
    user.platform_role = Role.PLATFORM_ADMIN
    user.approval_status = ApprovalStatus.APPROVED
    user.is_active = True
    await session.flush()

    credential = await session.get(LocalCredential, user.id)
    if credential is None:
        credential = LocalCredential(user_id=user.id, password_hash=password_hash)
        session.add(credential)
    else:
        credential.password_hash = password_hash
    credential.must_change_password = False
    credential.failed_attempts = 0
    credential.locked_until = None
    await session.flush()

    # Без членства администратор видит админку, но в портале у него нет пространства:
    # интерфейс не шлёт X-Workspace-Id. Пространство установки по умолчанию — `default`.
    if await identity_service.workspace_exists(session, DEV_WORKSPACE_ID):
        await users_service.upsert_membership(
            session, user_id=user.id, workspace_id=DEV_WORKSPACE_ID, role=Role.WORKSPACE_ADMIN
        )
    return user
