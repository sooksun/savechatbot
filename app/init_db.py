"""Create all tables. Run: python -m app.init_db"""
from .database import Base, engine
from . import models  # noqa: F401 register models


def main() -> None:
    Base.metadata.create_all(engine)
    print("Tables created.")


if __name__ == "__main__":
    main()
