import requests
import hashlib
from requests.exceptions import RequestException


class KeeneticRouter:
    def __init__(self, address, username, password, name):
        if not address.startswith("http"):
            if address.endswith("/"):
                address = address[:-1]
            address = f"http://{address}"
        self.base_url = address
        self.username = username
        self.password = password
        self.name = name
        self.session = requests.Session()
        self.csrf_token = None

    def login(self):
        try:
            # Начальный запрос для получения необходимых заголовков
            auth_url = f"{self.base_url}/auth"
            initial_response = self.session.get(auth_url, timeout=5)

            # Проверяем, требуется ли аутентификация
            if initial_response.status_code == 401:
                realm = initial_response.headers.get("X-NDM-Realm")
                challenge = initial_response.headers.get("X-NDM-Challenge")

                # Вычисляем MD5-хеш от комбинации логина, realm и пароля
                md5_hash = hashlib.md5(
                    f"{self.username}:{realm}:{self.password}".encode("utf-8")
                ).hexdigest()

                # Вычисляем SHA256-хеш от комбинации challenge и предыдущего MD5-хеша
                sha256_hash = hashlib.sha256(
                    f"{challenge}{md5_hash}".encode("utf-8")
                ).hexdigest()

                # Отправляем данные для аутентификации
                auth_data = {"login": self.username, "password": sha256_hash}
                auth_response = self.session.post(
                    auth_url, json=auth_data, timeout=5
                )

                if auth_response.status_code == 200:
                    return True
                else:
                    print(_("Authentication error."))
                    return False
            elif initial_response.status_code == 200:
                # Уже аутентифицированы
                return True
            else:
                print(_("Unknown error during authentication attempt."))
                return False
        except RequestException as e:
            print(_("Connection error with router {name}: {error}").format(name=self.name, error=e))
            return False

    def keen_request(self, endpoint, data=None):
        url = f"{self.base_url}/{endpoint}"
        try:
            if data:
                response = self.session.post(url, json=data, timeout=5)
            else:
                response = self.session.get(url, timeout=5)
            return response
        except RequestException as e:
            print(_("Request error with router {name}: {error}").format(name=self.name, error=e))
            return None

    def get_policies(self):
        if not self.login():
            return {}
        endpoint = "rci/show/rc/ip/policy"
        response = self.keen_request(endpoint)
        if response and response.status_code == 200:
            policies = response.json()
            return policies
        else:
            print(_("Error retrieving policies."))
            return {}


    def get_online_clients(self):
        if not self.login():
            return []

        # Получаем информацию о клиентах
        clients_endpoint = "rci/show/ip/hotspot/host"
        clients_response = self.keen_request(clients_endpoint)

        if not clients_response or clients_response.status_code != 200:
            print(_("Error retrieving client list."))
            return []

        clients_data = clients_response.json()
        clients_dict = {}
        for client in clients_data:
            mac = client.get("mac", "").lower()
            clients_dict[mac] = {
                "name": client.get("name", "Unknown"),
                "ip": client.get("ip", "N/A"),
                "mac": mac,
                "data": client,
                "policy": None,  # Мы заполним это позже
            }

        # Получаем информацию о политиках клиентов
        policies_endpoint = "rci/show/rc/ip/hotspot/host"
        policies_response = self.keen_request(policies_endpoint)

        if policies_response and policies_response.status_code == 200:
            policies_data = policies_response.json()
            for policy_info in policies_data:
                mac = policy_info.get("mac", "").lower()
                if mac in clients_dict:
                    clients_dict[mac]["policy"] = policy_info.get("policy", None)
                    clients_dict[mac]["access"] = policy_info.get("access", "deny")
                    clients_dict[mac]["permit"] = policy_info.get("permit", False)
                    clients_dict[mac]["deny"] = policy_info.get("deny", False)
                    clients_dict[mac]["priority"] = policy_info.get("priority", None)
                else:
                    # Если клиент отсутствует в списке клиентов, добавляем его
                    clients_dict[mac] = {
                        "name": "Unknown",
                        "ip": "N/A",
                        "mac": mac,
                        "online": False,
                        "policy": policy_info.get("policy", None),
                        "access": policy_info.get("access", "deny"),
                        "permit": policy_info.get("permit", False),
                        "deny": policy_info.get("deny", False),
                        "priority": policy_info.get("priority", None),
                    }

        # Преобразуем словарь в список
        online_clients = list(clients_dict.values())
        return online_clients

    def apply_policy_to_client(self, mac, policy):
        """Снимает блокировку с клиента и применяет к нему политику."""
        if not self.login():
            return False

        endpoint = "rci/ip/hotspot/host"
        data = {
            "mac": mac,
            "policy": policy if policy else False,
            "permit": True,
            "schedule": False,
        }
        response = self.keen_request(endpoint, data=data)
        if response and response.status_code == 200:
            # Можно дополнительно проверить ответ
            return True
        else:
            print(_("Error applying policy to client."))
            return False

    def apply_default_policy_to_client(self, mac):
        return self.apply_policy_to_client(mac, None)

    def get_wireguard_peers(self):
        if not self.login():
            return {}
        endpoint = "rci/show/interface/Wireguard"
        response = self.keen_request(endpoint)
        if response and response.status_code == 200:
            wg_data = response.json()
            return wg_data
        else:
            print(_("Error retrieving WireGuard settings."))
            return {}

    def set_client_block(self, mac):
        """Блокирует доступ клиента по MAC-адресу."""
        if not self.login():
            return False

        endpoint = "rci/ip/hotspot/host"

        data = {
            "mac": mac,
            "schedule": False,
            "deny": True,
        }

        response = self.keen_request(endpoint, data=data)
        if response and response.status_code == 200:
            return True
        else:
            print("Error applying deny flag to client.")
            return False

