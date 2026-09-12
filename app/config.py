"""进程级启动配置：只放需要部署期固定的项，运行时可变的走 settings 服务（数据库存储）。"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RECORDER_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = "127.0.0.1"
    port: int = 8000
    data_dir: Path = Path("data")          # 数据库 / 录制文件 / 日志的根目录
    panel_dir: Path = Path("panel/out")    # 前端静态产物目录
    access_token: str | None = None        # 可选访问令牌，设置后 REST 与 WS 均需携带
    log_level: str = "INFO"

    def resolve_paths(self, base_dir: Path) -> None:
        """把相对路径锚定到 recorder/ 目录，避免受进程工作目录影响。"""
        if not self.data_dir.is_absolute():
            self.data_dir = base_dir / self.data_dir
        if not self.panel_dir.is_absolute():
            self.panel_dir = base_dir / self.panel_dir


config = AppConfig()
