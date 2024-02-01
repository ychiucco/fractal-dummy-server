from typing import Optional

from pydantic import EmailStr
from sqlalchemy import Column
from sqlalchemy.types import JSON
from sqlmodel import Field
from sqlmodel import Relationship
from sqlmodel import SQLModel

from .linkuserproject import LinkUserProject


class OAuthAccount(SQLModel, table=True):

    __tablename__ = "oauthaccount"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user_oauth.id", nullable=False)
    user: Optional["UserOAuth"] = Relationship(back_populates="oauth_accounts")
    oauth_name: str = Field(index=True, nullable=False)
    access_token: str = Field(nullable=False)
    expires_at: Optional[int] = Field(nullable=True)
    refresh_token: Optional[str] = Field(nullable=True)
    account_id: str = Field(index=True, nullable=False)
    account_email: str = Field(nullable=False)

    class Config:
        orm_mode = True


class UserOAuth(SQLModel, table=True):

    __tablename__ = "user_oauth"

    id: Optional[int] = Field(default=None, primary_key=True)

    email: EmailStr = Field(
        sa_column_kwargs={"unique": True, "index": True}, nullable=False
    )
    hashed_password: str
    is_active: bool = Field(True, nullable=False)
    is_superuser: bool = Field(False, nullable=False)
    is_verified: bool = Field(False, nullable=False)

    slurm_user: Optional[str]
    slurm_accounts: list[str] = Field(
        sa_column=Column(JSON, server_default="[]", nullable=False)
    )
    cache_dir: Optional[str]
    username: Optional[str]

    oauth_accounts: list["OAuthAccount"] = Relationship(
        back_populates="user",
        sa_relationship_kwargs={"lazy": "joined", "cascade": "all, delete"},
    )
    project_list: list["Project"] = Relationship(  # noqa
        back_populates="user_list",
        link_model=LinkUserProject,
        sa_relationship_kwargs={"lazy": "selectin"},
    )

    class Config:
        orm_mode = True
