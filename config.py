# config.py
import json
import os

CONFIG_FILE = 'routers.json'

def load_routers():
    if os.path.exists(CONFIG_FILE):
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
