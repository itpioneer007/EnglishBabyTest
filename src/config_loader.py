"""
配置加载器

从 config.yaml 读取全局配置，提供统一的配置访问接口。
"""

import os
import yaml
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class DeviceConfig:
    serial: str = ""
    screen_resolution: tuple = (1080, 2400)


@dataclass
class AppConfig:
    package: str = "com.dinoenglish.yyb"
    activity: str = ""


@dataclass
class AccountConfig:
    username: str = ""
    password: str = ""


@dataclass
class OutputConfig:
    dir: str = "outputs"
    screenshot_dir: str = "outputs/screenshots"
    save_pass_screenshots: bool = False
    question_timeout: int = 120
    max_retries: int = 2


@dataclass
class FlowConfig:
    default_timeout: int = 10
    poll_interval: float = 1.0
    step_delay: float = 0.5


@dataclass
class Config:
    device: DeviceConfig = field(default_factory=DeviceConfig)
    app: AppConfig = field(default_factory=AppConfig)
    account: AccountConfig = field(default_factory=AccountConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    flow: FlowConfig = field(default_factory=FlowConfig)


def load_config(config_path: str = None) -> Config:
    """
    加载配置文件
    默认从项目根目录的 config.yaml 读取
    """
    if config_path is None:
        # 默认从本文件上级目录找 config.yaml
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config_path = os.path.join(project_root, "config.yaml")

    if not os.path.exists(config_path):
        print(f"⚠ 配置文件不存在: {config_path}，使用默认配置")
        return Config()

    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    config = Config()

    if "device" in data:
        d = data["device"]
        config.device = DeviceConfig(
            serial=d.get("serial", ""),
            screen_resolution=tuple(d.get("screen_resolution", [1080, 2400])),
        )

    if "app" in data:
        a = data["app"]
        config.app = AppConfig(
            package=a.get("package", "com.dinoenglish.yyb"),
            activity=a.get("activity", ""),
        )

    if "account" in data:
        acc = data["account"]
        config.account = AccountConfig(
            username=acc.get("username", ""),
            password=acc.get("password", ""),
        )

    if "output" in data:
        o = data["output"]
        config.output = OutputConfig(
            dir=o.get("dir", "outputs"),
            screenshot_dir=o.get("screenshot_dir", "outputs/screenshots"),
            save_pass_screenshots=o.get("save_pass_screenshots", False),
            question_timeout=o.get("question_timeout", 120),
            max_retries=o.get("max_retries", 2),
        )

    if "flow" in data:
        fl = data["flow"]
        config.flow = FlowConfig(
            default_timeout=fl.get("default_timeout", 10),
            poll_interval=fl.get("poll_interval", 1.0),
            step_delay=fl.get("step_delay", 0.5),
        )

    return config


if __name__ == "__main__":
    cfg = load_config()
    print("=== 当前配置 ===")
    print(f"设备序列号: {cfg.device.serial}")
    print(f"屏幕分辨率: {cfg.device.screen_resolution}")
    print(f"APP包名: {cfg.app.package}")
    print(f"账号: {cfg.account.username}")
    print(f"输出目录: {cfg.output.dir}")
