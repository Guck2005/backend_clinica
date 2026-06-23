from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


from app import models as _models  # noqa: E402,F401
