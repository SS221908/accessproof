from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    root: Path
    data_dir: Path
    artifacts_dir: Path
    api_key: str
    model: str
    base_url: str
    max_steps: int = 24
    public_origin: str = ""
    demo_password: str = ""
    require_demo_auth: bool = False


def get_settings() -> Settings:
    load_dotenv(ROOT / ".env", override=False)
    return Settings(
        root=ROOT,
        data_dir=Path(os.getenv("ACCESSPROOF_DATA_DIR", str(ROOT / ".data"))),
        artifacts_dir=Path(os.getenv("ACCESSPROOF_ARTIFACTS_DIR", str(ROOT / ".artifacts"))),
        api_key=os.getenv("NEBIUS_API_KEY", "").strip(),
        model=os.getenv("NEBIUS_MODEL", "nvidia/Nemotron-3.5-Super-VL"),
        base_url=os.getenv("NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1/"),
        max_steps=min(40, max(8, int(os.getenv("ACCESSPROOF_MAX_STEPS", "24")))),
        public_origin=os.getenv("ACCESSPROOF_PUBLIC_ORIGIN", "").strip() or os.getenv("RENDER_EXTERNAL_URL", "").strip(),
        demo_password=os.getenv("ACCESSPROOF_DEMO_PASSWORD", "").strip(),
        require_demo_auth=(
            os.getenv("ACCESSPROOF_REQUIRE_DEMO_AUTH", "").lower().strip() in {"true", "1", "yes", "on"}
            or os.getenv("RENDER", "").lower().strip() in {"true", "1", "yes", "on"}
        ),
    )
