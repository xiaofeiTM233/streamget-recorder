"""进程级启动配置：只放需要部署期固定的项，运行时可变的走 settings 服务（JSON 存储）。"""

import sys
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# 打包(PyInstaller)运行时：只读资源位于 _MEIPASS 解压目录，可写数据锚定 exe 所在目录；
# 源码运行时锚定项目根目录（本文件的上级目录）
FROZEN = getattr(sys, "frozen", False)
RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", "")) if FROZEN else Path(__file__).resolve().parent.parent
BASE_DIR = Path(sys.executable).resolve().parent if FROZEN else RESOURCE_DIR


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RECORDER_",
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = "127.0.0.1"
    port: int = 8000
    data_dir: Path = Path("data")          # 数据文件 / 录制文件 / 日志的根目录
    panel_dir: Path = RESOURCE_DIR / "panel" / "out" if FROZEN else Path("panel/out")  # 前端静态产物目录
    log_level: str = "INFO"

    def resolve_paths(self, base_dir: Path) -> None:
        """把相对路径锚定到根目录（打包后为 exe 所在目录），避免受进程工作目录影响。"""
        anchor = BASE_DIR if FROZEN else base_dir
        if not self.data_dir.is_absolute():
            self.data_dir = anchor / self.data_dir
        if not self.panel_dir.is_absolute():
            self.panel_dir = anchor / self.panel_dir


config = AppConfig()
