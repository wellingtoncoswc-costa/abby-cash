from alembic.config import Config
from alembic.script import ScriptDirectory


def test_single_alembic_head():
    assert len(ScriptDirectory.from_config(Config("alembic.ini")).get_heads()) == 1
