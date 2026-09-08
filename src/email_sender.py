"""
src/email_sender.py — 邮件发送
负责人：C

职责：
  1. 通过SMTP发送报告邮件
  2. 支持HTML格式 + 附件
  3. 配置从 data/export_config.json 读取

使用方式：
    sender = EmailSender()
    sender.send_report(to_email="teacher@school.com",
                       subject="Unit6审查报告",
                       html_body="<h1>...</h1>",
                       attachments=["report.html", "errors.csv"])

前置条件：
  需要配置 SMTP 服务器信息（在 export_config.json 或环境变量中）
"""

import json
from pathlib import Path
from typing import Optional


class EmailSender:
    """邮件报告发送器"""

    def __init__(self, config_path: str = None):
        config_file = Path(config_path or Path(__file__).parent.parent / "data" / "export_config.json")
        self.smtp_config = self._load_smtp(config_file)

    def _load_smtp(self, config_file: Path) -> dict:
        if config_file.exists():
            with open(config_file, "r", encoding="utf-8") as f:
                config = json.load(f)
                return {
                    "host": config.get("smtp_host", "smtp.qq.com"),
                    "port": config.get("smtp_port", 587),
                    "user": config.get("smtp_user", ""),
                    "password": config.get("smtp_password", ""),
                    "from_addr": config.get("smtp_from", ""),
                    "enabled": config.get("email_enabled", False),
                }
        return {"enabled": False}

    def send_report(self, to_email: str, subject: str,
                    html_body: str = "", attachments: list = None) -> dict:
        """
        发送报告邮件

        Returns:
            {"success": True/False, "message": "..."}
        """
        # ===== C 在这里实现 =====
        # TODO(C): 
        # import smtplib
        # from email.mime.multipart import MIMEMultipart
        # from email.mime.text import MIMEText
        # from email.mime.base import MIMEBase
        # from email import encoders
        #
        # msg = MIMEMultipart()
        # msg["From"] = self.smtp_config["from_addr"]
        # msg["To"] = to_email
        # msg["Subject"] = subject
        # msg.attach(MIMEText(html_body, "html"))
        #
        # for att in (attachments or []):
        #     with open(att, "rb") as f:
        #         part = MIMEBase("application", "octet-stream")
        #         part.set_payload(f.read())
        #     encoders.encode_base64(part)
        #     part.add_header("Content-Disposition", f'attachment; filename="{Path(att).name}"')
        #     msg.attach(part)
        #
        # server = smtplib.SMTP(self.smtp_config["host"], self.smtp_config["port"])
        # server.starttls()
        # server.login(self.smtp_config["user"], self.smtp_config["password"])
        # server.sendmail(self.smtp_config["from_addr"], to_email, msg.as_string())
        # server.quit()

        return {
            "success": False,
            "message": f"邮件发送功能待实现。请配置 SMTP 后在 src/email_sender.py 中完成。"
        }
