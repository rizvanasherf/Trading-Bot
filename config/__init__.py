from .settings import settings
from pathlib import Path
import yaml

_CONFIG_PATH = Path(__file__).parent / "config.yaml"


def load_config() -> dict:
    with open(_CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)


def save_config(data: dict) -> None:
    with open(_CONFIG_PATH, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)
