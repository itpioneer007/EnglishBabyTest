# -*- coding: utf-8 -*-
"""
C5  邮件发送
===========
跑完把报告发到老师邮箱（分工文档 5.5）。
注意：
  - QQ/163 邮箱要用"授权码"而不是登录密码（去邮箱设置里开 SMTP 服务拿授权码）。
  - 正式项目请把账号密码放到环境变量，不要写死在代码里，避免上传 GitHub 泄露。
依赖：Python 自带 smtplib，无需额外安装。
"""

import os
import smtplib
from email.header import Header
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication


class EmailSender:
    """邮件发送器。"""

    def send_report(self, to_email: str, subject: str,
                    html_body: str = "", attachments: list = None) -> dict:
        """
        输入：收件人、主题、HTML正文、附件路径列表
        输出（按文档 5.5）：{"success": True/False, "message": "..."}
        """
        # 从环境变量读账号（避免密码写死进 git）
        user = os.environ.get("EMAIL_USER", "")
        password = os.environ.get("EMAIL_PASSWORD", "")
        smtp_host = os.environ.get("EMAIL_SMTP_HOST", "smtp.qq.com")
        smtp_port = int(os.environ.get("EMAIL_SMTP_PORT", "465"))

        if not user or not password:
            return {"success": False,
                    "message": "未配置 EMAIL_USER / EMAIL_PASSWORD 环境变量，发邮件已跳过"}

        try:
            msg = MIMEMultipart()
            msg["From"] = user
            msg["To"] = to_email
            msg["Subject"] = Header(subject, "utf-8")
            if html_body:
                msg.attach(MIMEText(html_body, "html", "utf-8"))

            for item in (attachments or []):
                # 支持两种写法：纯路径字符串，或 (路径, 显示名) 元组
                if isinstance(item, (tuple, list)):
                    path, disp = item[0], item[1]
                else:
                    path, disp = item, os.path.basename(item)
                if os.path.exists(path):
                    with open(path, "rb") as f:
                        part = MIMEApplication(f.read())
                        # 显示名做 ASCII 兼容编码，避免中文附件名乱码
                        part.add_header("Content-Disposition", "attachment",
                                        filename=("utf-8", "B", disp))
                        msg.attach(part)

            with smtplib.SMTP_SSL(smtp_host, smtp_port) as server:
                server.login(user, password)
                server.send_message(msg)
            return {"success": True, "message": f"已发送至 {to_email}"}
        except Exception as e:
            return {"success": False, "message": f"发送失败：{e}"}
