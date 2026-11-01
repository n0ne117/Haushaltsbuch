from alembic import context
from sqlalchemy import engine_from_config, pool

from app.models import Base

config = context.config


def run_migrations() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=Base.metadata,
            render_as_batch=True,  # SQLite needs batch mode for ALTER
        )
        with context.begin_transaction():
            context.run_migrations()


run_migrations()
