import json
import os
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "keenetic-manager"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_FILE = CONFIG_DIR / "routers.json"

def load_routers():
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, 'r') as f:
                routers = json.load(f)
                return routers
        except Exception as e:
            print(f"Ошибка загрузки роутеров: {e}")
            return []
    else:
        return []

def save_routers(routers):
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(routers, f)
    except Exception as e:
        print(f"Ошибка сохранения роутеров: {e}")
