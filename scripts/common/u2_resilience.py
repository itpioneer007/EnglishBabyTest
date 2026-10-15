# -*- coding: utf-8 -*-
"""补全 uiautomator2 的异常映射缺口，让"设备瞬断"能走库自带的自愈重试。

═══ 问题（uiautomator2 3.7.0 / core.py）═══
  AdbHTTPConnection 继承 http.client.HTTPConnection，但其 socket 来自 adbutils
  （不是 requests）。于是底层抛出的是 http.client 家族异常：
      RemoteDisconnected / BadStatusLine / ConnectionResetError
  实测类型层次：
      RemoteDisconnected → ConnectionResetError → ConnectionError → OSError
                        → BadStatusLine → HTTPException → Exception
      issubclass(RemoteDisconnected, requests.RequestException)  ==  False   ← 关键
  而 core.py:_http_request() 的 except 只兜：
      except requests.Timeout / except requests.RequestException
  → 该异常【裸逃逸】；再往上的 jsonrpc_call() 自愈分支只捕获：
      except (HTTPError, UiAutomationNotConnectedError)
  → 【不触发 stop_uiautomator() + start_uiautomator() + 重试】
  → 一个设备瞬断直接掀翻整个模块（实测：口语训练跑 76s 后
     RemoteDisconnected → 该模块 0 题、整轮判定作废）。

═══ 修法 ═══
  把 http.client / ConnectionError 家族**映射成库自己的 HTTPError** ——
  这正是库本来就想做、只是漏做的一步（它已把 requests.* 映射成 HTTPError）。
  映射后，jsonrpc_call 既有的"重启服务并重试一次"自愈路径自动生效。

  只改这一处、不改调用方，也不改任何模块代码。

用法：`import common.u2_resilience`（导入即自动 install，幂等）。
"""
import http.client
import socket

_INSTALLED = False


def install() -> bool:
    """打补丁；已打过或环境不可用则返回 False（绝不抛异常）。"""
    global _INSTALLED
    if _INSTALLED:
        return False
    try:
        from uiautomator2 import core as _core
        from uiautomator2.exceptions import HTTPError as _U2HTTPError
    except Exception:
        return False

    _orig = getattr(_core, "_http_request", None)
    if _orig is None or getattr(_orig, "_yyb_patched", False):
        return False

    def _http_request(dev, device_port, method, path, data=None,
                      timeout=10.0, print_request=False):
        try:
            return _orig(dev, device_port, method, path, data, timeout, print_request)
        except (http.client.HTTPException, ConnectionError, socket.timeout, TimeoutError) as e:
            # ★ RemoteDisconnected 同时属于 ConnectionResetError(→ConnectionError)
            #   与 BadStatusLine(→HTTPException)，两条血缘都在这里收口。
            #   映射成 HTTPError 后，BasicUiautomatorServer.jsonrpc_call 会
            #   stop/start uiautomator 并重试一次 —— 设备瞬断即可自愈。
            raise _U2HTTPError(f"HTTP request failed: {type(e).__name__}: {e}") from e

    _http_request._yyb_patched = True
    _core._http_request = _http_request
    _INSTALLED = True
    return True


install()
