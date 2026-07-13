from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


from app.db.models import core as _core  # noqa: E402,F401
