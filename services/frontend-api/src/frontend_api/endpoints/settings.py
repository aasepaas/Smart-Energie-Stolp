"""System settings (administrators only)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path

from .. import query_builder
from ..authentication import ADMINS, Principal, allow
from ..query_executor import Session, get_session
from ..schemas import SETTING_KEY_PATTERN, Setting, SettingValue

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=list[Setting])
def list_settings(user: Principal = allow(*ADMINS),
                  db: Session = Depends(get_session, scope="function")):
    return query_builder.list_settings(db)


@router.put("/{key}", response_model=Setting)
def put_setting(key: Annotated[str, Path(pattern=SETTING_KEY_PATTERN)], body: SettingValue,
                user: Principal = allow(*ADMINS),
                db: Session = Depends(get_session, scope="function")):
    """Creates or replaces one setting; the value is any JSON value except null."""
    return query_builder.put_setting(db, key, body.value)
