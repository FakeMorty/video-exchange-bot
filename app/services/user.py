def get_display_name(user: "User") -> str:
    if user.display_name:
        return user.display_name
    if user.first_name:
        return user.first_name
    if user.username:
        return f"@{user.username}"
    return f"User#{user.telegram_id}"


def is_admin_or_super(telegram_id: int, user: "User" = None) -> bool:
    if telegram_id in ADMINS:
        return True
    if user and user.is_admin:
        return True
    return False


# ============================
# ЛОГИРОВАНИЕ БАЛАНСА И ДЕЙСТВИЙ
# ============================
async def log_balance_change(
    session: AsyncSession,
    user: "User",
    amount: Decimal,
    source: str,
    source_id: int = None,
    admin_id: int = None,
    details: str = None,
):
    log = BalanceLog(
        user_id=user.id,
        amount=amount,
        balance_before=user.balance,
        balance_after=user.balance + amount,
        source=source,
        source_id=source_id,
        admin_id=admin_id,
        details=details,
    )
    session.add(log)


async def log_user_action(
    session: AsyncSession,
    user_id: int,
    action: str,
    details: str = None,
    *,
    auto_commit: bool = True,
):
    log = UserActionLog(user_id=user_id, action=action, details=details)
    session.add(log)
    if auto_commit:
        try:
            await session.commit()
        except Exception:
            await session.rollback()


# ============================
# ПОЛУЧЕНИЕ ПОЛЬЗОВАТЕЛЕЙ
# ============================
async def get_user(session: AsyncSession, telegram_id: int) -> "User | None":
    return (await session.execute(
        select(User).where(User.telegram_id == telegram_id)
    )).scalar_one_or_none()


async def get_user_by_id(session: AsyncSession, user_id: int) -> "User | None":
    return (await session.execute(
        select(User).where(User.id == user_id)
    )).scalar_one_or_none()


async def get_user_by_username(session: AsyncSession, username: str) -> "User | None":
    if username.startswith("@"):
        username = username[1:]
    return (await session.execute(
        select(User).where(User.username == username)
    )).scalar_one_or_none()


async def get_user_by_display_name(session: AsyncSession, display_name: str) -> "User | None":
    return (await session.execute(
        select(User).where(User.display_name == display_name)
    )).scalar_one_or_none()


async def get_or_create_user(
    session: AsyncSession,
    telegram_id: int,
    username: str = None,
    first_name: str = None,
    last_name: str = None,
    referral_code: str = None,
) -> tuple["User", bool]:
    user = await get_user(session, telegram_id)
    if user:
        user.username = username
        user.first_name = first_name
        user.last_name = last_name
        await session.commit()
        return user, False

    referred_by = None
    starting_bonus = to_decimal(STARTING_BALANCE)
    if referral_code:
        inviter = (await session.execute(
            select(User).where(User.referral_code == referral_code)
        )).scalar_one_or_none()
        if inviter and inviter.telegram_id != telegram_id:
            referred_by = inviter.id

    user = User(
        telegram_id=telegram_id,
        username=username,
        first_name=first_name,
        last_name=last_name,
        balance=starting_bonus,
        referral_code=uuid.uuid4().hex[:8],
        referred_by_user_id=referred_by,
    )
    session.add(user)
    await session.flush()
    await log_balance_change(session, user, starting_bonus, "registration",
                             details=f"Starting balance. Referred by: {referred_by}")
    await session.commit()
    await log_user_action(session, user.id, "registration",
                          f"tg_id={telegram_id}, referred_by={referred_by}")
    return user, True


# ============================
# НИКНЕЙМ
# ============================
async def set_display_name(session: AsyncSession, user: "User", name: str) -> tuple[bool, str]:
