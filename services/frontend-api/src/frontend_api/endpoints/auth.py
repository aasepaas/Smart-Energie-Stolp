"""Login, token refresh and logout."""

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status

from .. import authentication, config, query_builder
from ..authentication import Principal, current_user
from ..query_executor import Session, get_login_session
from ..schemas import CurrentUser, LoginRequest, TokenResponse

router = APIRouter(prefix="/auth", tags=["authentication"])


def _issue_tokens(response: Response, user: Principal, email: str) -> TokenResponse:
    response.set_cookie(
        config.REFRESH_COOKIE_NAME,
        authentication.create_refresh_token(user.user_id, email),
        max_age=config.REFRESH_TOKEN_HOURS * 3600,
        path=config.REFRESH_COOKIE_PATH,
        secure=config.REFRESH_COOKIE_SECURE,
        httponly=True,
        samesite="strict",
    )
    return TokenResponse(
        access_token=authentication.create_access_token(user),
        expires_in=config.ACCESS_TOKEN_MINUTES * 60,
        user=CurrentUser(id=user.user_id, role=user.role, participant_id=user.participant_id),
    )


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, response: Response,
          db: Session = Depends(get_login_session, scope="function")):
    """Checks email and password; returns an access token and sets the refresh cookie."""
    account = query_builder.account_by_email(db, body.email)
    if not authentication.verify_password(account and account["password_hash"], body.password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    user = authentication.principal(account["user_id"], account["role"], account["participant_id"])
    return _issue_tokens(response, user, body.email)


@router.post("/refresh", response_model=TokenResponse)
def refresh(response: Response,
            refresh_token: str | None = Cookie(None, alias=config.REFRESH_COOKIE_NAME),
            db: Session = Depends(get_login_session, scope="function")):
    """New access token from the refresh cookie. The account is loaded again, so a changed
    role or a deleted account takes effect at the next refresh."""
    if not refresh_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Refresh token missing")
    user_id, email = authentication.decode_refresh_token(refresh_token)
    account = query_builder.account_by_email(db, email)
    if account is None or account["user_id"] != user_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account no longer exists")
    user = authentication.principal(account["user_id"], account["role"], account["participant_id"])
    return _issue_tokens(response, user, email)


@router.post("/logout", status_code=204)
def logout(response: Response):
    """Removes the refresh cookie. The access token stays valid until it expires."""
    response.delete_cookie(
        config.REFRESH_COOKIE_NAME,
        path=config.REFRESH_COOKIE_PATH,
        secure=config.REFRESH_COOKIE_SECURE,
        httponly=True,
        samesite="strict",
    )


@router.get("/me", response_model=CurrentUser)
def me(user: Principal = Depends(current_user)):
    """The logged in user, from the access token."""
    return CurrentUser(id=user.user_id, role=user.role, participant_id=user.participant_id)
