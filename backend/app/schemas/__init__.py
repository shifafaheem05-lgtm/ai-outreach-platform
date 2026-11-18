from app.core.validation import check_password
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class RegisterIn(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("password")
    @classmethod
    def _pw(cls, v: str) -> str:
        return check_password(v)
    organization_name: str = Field(min_length=1, max_length=200)


class ChangePasswordIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def _pw(cls, v: str) -> str:
        return check_password(v)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class RefreshIn(BaseModel):
    refresh_token: str


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: str
    name: str
    role: str
    org_id: int
