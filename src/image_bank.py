"""
image_bank.py — 教材配图参考库

用途: 从本地图片文件夹加载参考图片, 按文件名关键词索引
      审查时用这些参考图跟实际截图做对比, 判断配图是否正确
"""

import re
import glob
from pathlib import Path
from typing import Optional


class ImageBank:
    """
    教材参考图库
    
    数据来源: D:\\压缩包存储\\听力专项新湘鲁六上U6-9\\U6图片\\ 等
    
    图片文件名 = 图片描述关键词 (中文)
    索引方式: 中文文件名 + 知识库英文词汇(自动关联)
    """

    DEFAULT_BASE = r"D:\压缩包存储"

    def __init__(self, base_dirs: list = None):
        # 优先级: 传参 > config.yaml > DEFAULT_BASE
        self.base_dirs = []
        if base_dirs:
            self.base_dirs = [Path(d) for d in (base_dirs if isinstance(base_dirs, list) else [base_dirs])]
        else:
            try:
                cfg_path = Path(__file__).parent.parent / "config.yaml"
                if cfg_path.exists():
                    import yaml
                    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
                    d = cfg.get("image_dir", [])
                    if isinstance(d, str):
                        self.base_dirs = [Path(d)]
                    elif isinstance(d, list):
                        self.base_dirs = [Path(x) for x in d]
            except Exception:
                pass
        # 如果都没配, 用默认值并在DEFAULT_BASE下找 U*图片/ 目录
        if not self.base_dirs:
            self.base_dirs = [Path(self.DEFAULT_BASE)]
        self.index: dict = {}
        self._loaded = False

    def load(self, unit: int = None):
        """加载所有目录中指定单元的图片"""
        dirs_found = []
        for base_dir in self.base_dirs:
            if not base_dir.exists():
                print(f"[ImageBank] 目录不存在: {base_dir}")
                continue
            if unit:
                dirs_found.extend(base_dir.glob(f"U{unit}图片*"))
            else:
                dirs_found.extend(base_dir.glob("U*图片*"))

        if not dirs_found:
            print(f"[ImageBank] 在 {[str(d) for d in self.base_dirs]} 下未找到 U*图片* 目录")
            return

        for d in sorted(set(dirs_found)):
            if not d.exists():
                continue
            m = re.search(r'U(\d+)', d.name)
            if not m:
                continue
            u = int(m.group(1))
            for img_path in sorted(d.iterdir()):
                if img_path.suffix.lower() not in ('.png', '.jpg', '.jpeg', '.gif', '.bmp'):
                    continue
                stem = img_path.stem
                clean_name = re.sub(r'[（(]\d+[)）]', '', stem).strip()
                # 中文全名作为关键词
                self._add_index(u, clean_name.lower(), str(img_path))
                # 每个中文词也单独索引
                for word in re.findall(r'[\u4e00-\u9fff]{2,}', clean_name):
                    self._add_index(u, word.lower(), str(img_path))

        # 用知识库关联英文词汇
        self._build_en_index(unit)

        self._loaded = True
        all_paths = set()
        for paths in self.index.values():
            all_paths.update(paths)
        print(f"[ImageBank] 加载 {len(self.index)} 条索引, {len(all_paths)} 张图片")

    def _build_en_index(self, unit: int = None):
        """移除 — 改用 _english_to_chinese 启发式匹配"""
        pass

    def _add_index(self, unit: int, keyword: str, path: str):
        key = (unit, keyword)
        if key not in self.index:
            self.index[key] = []
        if path not in self.index[key]:
            self.index[key].append(path)

    def find_matches(self, unit: int, keywords: list[str]) -> list[str]:
        """根据关键词列表找匹配的参考图片"""
        if not self._loaded:
            self.load(unit)

        matched_paths = []
        for kw in keywords:
            kw_lower = kw.lower().strip()
            if not kw_lower:
                continue

            # 1. 精确匹配中文索引
            key = (unit, kw_lower)
            if key in self.index:
                matched_paths.extend(self.index[key])

            # 2. 部分匹配中文索引 (中文字词)
            for (u, indexed_kw), paths in self.index.items():
                if u == unit:
                    if kw_lower in indexed_kw or indexed_kw in kw_lower:
                        matched_paths.extend(paths)

            # 3. 如果是英文词, 用知识库翻译成中文后再匹配
            if re.match(r'^[a-zA-Z]+$', kw_lower):
                chinese = self._english_to_chinese(unit, kw_lower)
                for cn in chinese:
                    for (u, indexed_kw), paths in self.index.items():
                        if u == unit:
                            if cn in indexed_kw or indexed_kw in cn:
                                matched_paths.extend(paths)

        # 去重
        seen = set()
        unique = []
        for p in matched_paths:
            if p not in seen:
                seen.add(p)
                unique.append(p)
        return unique[:3]

    def _english_to_chinese(self, unit: int, en_word: str) -> list[str]:
        """
        用知识库 + 文件名启发式匹配, 找到英文词汇对应的中文描述
        
        策略: 遍历该单元所有中文文件名, 看哪个文件名可能是 en_word 的翻译
        """
        candidates = []
        try:
            from src.knowledge_base import KnowledgeBase
            kb = KnowledgeBase()

            # 1. 找出该单元知识库里所有词汇
            unit_vocab = []
            for version_key, info in kb.data.items():
                if str(unit) in info.get("units", {}):
                    unit_vocab = info["units"][str(unit)].get("vocab", [])
                    break

            # 2. 遍历该单元的中文图片文件名
            for (u, indexed_kw), paths in self.index.items():
                if u != unit:
                    continue
                # indexed_kw 是中文, 检查它是否是 en_word 的翻译
                # 方法: 用对应知识库中的中英文对照
                # 实际上我们不知道, 所以用启发式:
                # 如果 indexed_kw 包含"车"且 en_word 是"truck"/"car"/"bicycle"
                heuristic_map = {
                    '车': ['truck', 'car', 'bus', 'taxi', 'ambulance', 'van'],
                    '自行车|单车': ['bicycle', 'bike', 'cycle', 'cycling', 'ride'],
                    '扫地|打扫': ['sweep', 'sweeping', 'clean', 'cleaning', 'cleaned', 'mop'],
                    '水|水龙头|水桶': ['water', 'tap', 'bucket', 'rain', 'rainwater'],
                    '树|森林': ['tree', 'plant', 'planting', 'planted', 'wood', 'forest'],
                    '垃圾|废': ['trash', 'garbage', 'waste', 'rubbish', 'dump', 'litter'],
                    '教室|课堂': ['classroom', 'school', 'lesson', 'class'],
                    '太阳|晒': ['sun', 'solar', 'sunlight', 'sunny', 'shine'],
                    '风': ['wind', 'air', 'breeze'],
                    '能|能源': ['energy', 'power', 'solar', 'electric'],
                    '路|道路': ['road', 'street', 'walk', 'path', 'sidewalk'],
                    '帮助|扶|救': ['help', 'assist', 'aid', 'support', 'rescue', 'save'],
                    '食物|吃|喝|给': ['food', 'feed', 'eat', 'drink', 'give', 'meal', 'rice', 'bread'],
                    '警察': ['police', 'cop', 'officer'],
                    '关|关灯': ['turn off', 'close', 'shut', 'off'],
                    '种|植树': ['plant', 'grow', 'seed', 'tree', 'forest'],
                    '河|江|湖|海': ['river', 'lake', 'sea', 'ocean', 'water'],
                    '冰|冻': ['ice', 'frozen', 'glacier', 'freeze', 'cold', 'snow'],
                    '沙|漠': ['desert', 'sand', 'dry', 'drought'],
                    '金|金子|玉': ['gold', 'silver', 'jade', 'treasure', 'diamond', 'money'],
                    '座|让座|座位': ['seat', 'sit', 'chair', 'bench', 'sitting'],
                    '书|读|看|课本': ['book', 'read', 'reading', 'study', 'learn'],
                    '过马路|路': ['road', 'street', 'cross', 'crossing', 'sidewalk'],
                    '物理': ['physics', 'science', 'physical'],
                    '地理': ['geography', 'earth', 'world'],
                    '热心|善': ['kind', 'warm', 'friendly', 'helpful', 'nice', 'good'],
                    '烟|工厂烟': ['smoke', 'factory', 'smog', 'pollution', 'chimney'],
                    '煤|燃|烧': ['burn', 'coal', 'fire', 'flame', 'energy'],
                    '煮|沸': ['boil', 'cook', 'hot', 'heat'],
                    '操|操场': ['playground', 'field', 'sport', 'exercise', 'run'],
                    '水壶|瓶': ['bottle', 'plastic', 'container', 'cup', 'glass'],
                }
                for ch_char, en_list in heuristic_map.items():
                    # 拆开"金|金子|玉"逐个匹配
                    for ch_part in ch_char.split('|'):
                        if ch_part in indexed_kw:
                            for en in en_list:
                                if en_word in en or en in en_word:
                                    candidates.append(indexed_kw)
                                    break

            # 3. 直接在文件名中搜中文词的拼音首字母? 太复杂, 跳过
            return list(set(candidates))[:3]
        except Exception:
            return []

    def find_for_question(self, unit: int, recording: str, answer: str,
                          options: list[str], stem: str) -> list[str]:
        """为一道题找匹配的参考图片"""
        keywords = []

        # 答案对应的选项内容
        if answer and answer in 'ABC':
            opt_map = {'A': 0, 'B': 1, 'C': 2}
            if answer in opt_map and opt_map[answer] < len(options):
                kw = re.sub(r'^[A-C][\.\、\s]+', '', options[opt_map[answer]]).strip()
                if kw:
                    keywords.append(kw)

        # 录音中的英文单词
        if recording:
            eng_words = re.findall(r'[a-zA-Z]+', recording)
            keywords.extend(eng_words)

            # 对长录音, 取其中关键词
            if len(eng_words) > 3:
                # 用 stopwords 过滤, 只保留实义词
                stopwords = {'the','a','an','is','was','are','were','to','in','on',
                           'at','of','for','and','or','with','his','her','its',
                           'this','that','these','those','has','have','had',
                           'do','does','did','can','could','will','would',
                           'need','needs','we','he','she','it','they','my',
                           'your','our','their','not','no','by','from','up',
                           'out','about','how','what','who','when','where','why'}
                important = [w for w in eng_words if w.lower() not in stopwords]
                if important:
                    keywords = important  # 只保留实义词

        # stem 中的中文描述
        if stem:
            cn_words = re.findall(r'[\u4e00-\u9fff]{2,}', stem)
            keywords.extend(cn_words)

        # 所有选项
        for opt in options:
            clean = re.sub(r'^[A-C][\.\、\s]+', '', opt).strip()
            if clean:
                keywords.append(clean)

        return self.find_matches(unit, keywords)

    def count_images(self) -> dict:
        if not self._loaded:
            self.load()
        counts = {}
        for (unit, _), paths in self.index.items():
            counts.setdefault(unit, set()).update(paths)
        return {u: len(p) for u, p in counts.items()}


if __name__ == "__main__":
    bank = ImageBank()
    bank.load(6)
    print(f"U6: {bank.count_images().get(6, 0)}张")
    tests = [
        ("truck", "A", [], ""),
        ("sweep the floor", "A", ["A. Sweeping", "B. Reading", "C. Playing"], ""),
        ("gold", "A", [], ""),
        ("bicycle", "B", ["A. Car", "B. Bicycle", "C. Bus"], ""),
    ]
    for rec, ans, opts, stem in tests:
        refs = bank.find_for_question(6, rec, ans, opts, stem)
        print(f'  {rec:20s} → {[Path(p).stem for p in refs]}')
