"""Environment-based settings; no provider credentials are hardcoded."""
from dataclasses import dataclass
from pathlib import Path
import os


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    db_path: Path
    consultation_cooldown_seconds: int = 60
    qrng_primary: str = "qci"
    qrng_fallback: str = "anu"
    qrng_minimum_balance: int = 1


def get_settings() -> Settings:
    data_dir = Path(os.environ.get("GNOSIS_DATA_DIR", str(Path.home() / ".gnosis"))).expanduser().resolve()
    db_path = Path(os.environ.get("GNOSIS_DB_PATH", str(data_dir / "gnosis.sqlite3"))).expanduser().resolve()
    cooldown = int(os.environ.get("GNOSIS_COOLDOWN_SECONDS", "60"))
    if cooldown < 0: raise ValueError("Cooldown cannot be negative")
    return Settings(data_dir=data_dir, db_path=db_path, consultation_cooldown_seconds=cooldown)
