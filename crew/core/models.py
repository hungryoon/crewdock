from dataclasses import dataclass


@dataclass
class Instance:
    name: str
    type: str
    port: int
    image: str
    previous_image: str = ""
    timezone: str = ""
    state: str = "unknown"       # running | stopped | absent | unknown
    health: str = "unknown"      # ok | down | unknown
    created_at: str = ""

    @property
    def dashboard_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/"
