from __future__ import annotations

from sqlalchemy import Integer, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class AccountApplicationRow(Base):
    __tablename__ = "account_application"

    account_id: Mapped[str] = mapped_column(Text, primary_key=True)
    application_id: Mapped[str] = mapped_column(Text, primary_key=True)
    status: Mapped[int | None] = mapped_column(Integer)
    access_token: Mapped[str | None] = mapped_column(Text)
    info_message: Mapped[str | None] = mapped_column(Text)
    store: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)


class JwtRow(Base):
    __tablename__ = "jwt"

    jti: Mapped[str] = mapped_column(Text, primary_key=True)
    expires_at: Mapped[int] = mapped_column(Integer, nullable=False)


class SessionRow(Base):
    __tablename__ = "sessions"

    sid: Mapped[str] = mapped_column(Text, primary_key=True)
    session_json: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[int] = mapped_column(Integer, nullable=False)
