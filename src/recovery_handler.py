"""
src/recovery_handler.py — 异常恢复处理
负责人：B

职责：处理巡检中的广告弹窗 / 加载超时 / APP崩溃
"""

import time
import random


class RecoveryHandler:
    """异常恢复处理器"""

    MAX_RETRIES = 3

    def __init__(self, adb):
        self.adb = adb
        self.retry_count = {}
        self._backoff_secs = [2, 5, 10]  # 递增等待

    # ============================================
    # 弹窗 & 加载
    # ============================================

    def handle_ad_popup(self, elements) -> bool:
        """检测并关闭广告弹窗。返回 True 如果关了弹窗"""
        close_texts = ['关闭', '跳过', '×', '知道了', '确定', '取消',
                       '先走一步', '继续练习', '我知道了', '以后再说']
        skip_areas = []
        for e in elements:
            t = (e.text or '').strip()
            for kw in close_texts:
                if kw in t:
                    skip_areas.append((e.center, kw))
                    break
        if skip_areas:
            for center, kw in skip_areas:
                self.adb.tap(center[0], center[1])
                time.sleep(0.8)
                print(f"  [Recovery] 关闭弹窗 '{kw}' at {center}")
            return True
        return False

    def handle_loading(self, elements) -> bool:
        """检测加载状态，等一等"""
        all_text = ' '.join([(e.text or '') for e in elements])
        if any(k in all_text for k in ['加载中', 'Loading', '请稍候', '正在加载']):
            time.sleep(3)
            return True
        return False

    # ============================================
    # 崩溃恢复
    # ============================================

    def handle_crash(self) -> bool:
        """回到首页：连续按返回。不重启APP，不清缓存。"""
        try:
            from src.universe_navigator import UniverseNavigator
            nav = UniverseNavigator(self.adb)
            return nav.universal_reset()
        except Exception as e:
            print(f"  [Recovery] 返回首页失败: {e}")
            return False

    # ============================================
    # 综合性恢复（巡检循环调用的入口）
    # ============================================

    def attempt_recovery(self, elements: list, module_key: str) -> bool:
        """
        巡检循环中每次 dump_ui 后调用此方法
        依次尝试：弹窗 → 加载 → 崩溃恢复
        返回 True 表示需要重新 dump（页面变化了）
        """
        # 1. 弹窗
        if self.handle_ad_popup(elements):
            return True

        # 2. 加载中
        if self.handle_loading(elements):
            return True

        # 3. 没有元素且连续发生 → 可能崩溃
        if not elements or len(elements) < 5:
            self.record_failure(module_key)
            if self.should_skip(module_key):
                print(f"  [Recovery] {module_key} 已达最大重试次数，跳过")
                return False
            print(f"  [Recovery] UI元素异常少 ({len(elements)})，尝试恢复...")
            if self.handle_crash():
                self.reset(module_key)
                return True
            return False

        return False

    # ============================================
    # 重试计数
    # ============================================

    def should_skip(self, module_key: str) -> bool:
        return self.retry_count.get(module_key, 0) >= self.MAX_RETRIES

    def record_failure(self, module_key: str):
        self.retry_count[module_key] = self.retry_count.get(module_key, 0) + 1

    def reset(self, module_key: str = None):
        if module_key:
            self.retry_count.pop(module_key, None)
        else:
            self.retry_count.clear()
