#!/usr/bin/env python3
"""统一资源定位层（ResourceResolver）。

所有相对路径以 episode_dir 为基准解析，杜绝每个函数自行解析、
基准不一致导致的路径错误（如主题包手素材找不到、回退到马克笔）。

主题路径特殊处理：state.json / script.json 中的 theme 字段可能写为
相对于 episode_dir（如 ../../themes/xxx）或相对于项目根（如 themes/xxx），
自动探测哪种写法存在，保持向后兼容。

项目根自动探测：从 episode_dir 向上找包含 SKILL.md 的目录；
找不到时回退到 episode_dir 的上级的上级（projects/<ep> → 仓库根）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


class ResourceResolver:
    """统一资源定位：以 episode_dir 为基准解析所有相对路径。"""

    def __init__(self, episode_dir: Path):
        self.episode_dir = Path(episode_dir).resolve()
        self.project_root = self._find_project_root(self.episode_dir)

    # ------------------------------------------------------------------ 路径解析

    def resolve(self, path: str | Path) -> Path:
        """解析路径：绝对路径直接返回；相对路径以 episode_dir 为基准。"""
        p = Path(path)
        if p.is_absolute():
            return p
        return (self.episode_dir / p).resolve()

    def resolve_theme(self, theme_path: str | Path) -> Path | None:
        """解析主题目录路径。

        依次尝试三种基准，取第一个存在的：
        1. 相对于 episode_dir（如 ../../themes/xxx）
        2. 相对于项目根（如 themes/xxx）
        3. 绝对路径（已在 resolve 中处理）
        """
        p = Path(theme_path)
        if p.is_absolute():
            return p if p.exists() else None

        # 1. 相对于 episode_dir
        rel_ep = (self.episode_dir / p).resolve()
        if rel_ep.exists():
            return rel_ep if rel_ep.is_dir() else rel_ep.parent

        # 2. 相对于项目根
        rel_root = (self.project_root / p).resolve()
        if rel_root.exists():
            return rel_root if rel_root.is_dir() else rel_root.parent

        return None

    def resolve_theme_from_state(self) -> Path | None:
        """从 state.json 读取 theme 字段并解析；state 中没有则回退 script.json。"""
        raw = self._read_theme_field(self.episode_dir / "state.json")
        if not raw:
            raw = self._read_theme_field(self.episode_dir / "input" / "script.json")
        if not raw:
            return None
        return self.resolve_theme(raw)

    # ------------------------------------------------------------------ 手素材

    def resolve_hand(self, hand_arg: str | None = None) -> Path:
        """解析手素材路径。

        优先级：--hand > 主题包 hands[0] > 当期 assets/hand-chalk.png >
        当期 assets/hand-pen.png > 引擎默认。

        主题声明了手素材（如 chalk 主题的粉笔手）就以主题为准——
        马克笔配黑板是素材错配。
        """
        if hand_arg:
            hand = self.resolve(hand_arg)
            if not hand.exists():
                sys.exit(f"手笔素材不存在：{hand}")
            return hand

        # 主题包 hands
        theme = self.resolve_theme_from_state()
        if theme is not None:
            tj = theme / "theme.json"
            if tj.exists():
                try:
                    hands = json.loads(tj.read_text(encoding="utf-8")).get("hands") or []
                except (OSError, json.JSONDecodeError):
                    hands = []
                for h in hands:
                    f = theme / str(h.get("file", ""))
                    if f.exists():
                        return f

        # 当期 assets（优先粉笔，回退马克笔）
        for name in ("hand-chalk.png", "hand-pen.png"):
            legacy = self.episode_dir / "assets" / name
            if legacy.exists():
                return legacy

        sys.exit("手笔素材不存在（--hand / 主题 hands / assets/hand-*.png 均缺失）")

    # ------------------------------------------------------------------ 内部

    @staticmethod
    def _find_project_root(start: Path) -> Path:
        """从 episode_dir 向上找包含 SKILL.md 的目录作为项目根。"""
        p = start
        while p != p.parent:
            if (p / "SKILL.md").exists():
                return p
            p = p.parent
        # fallback：projects/<ep> 的上级的上级 = 仓库根
        return start.parent.parent if start.parent.parent.exists() else start

    @staticmethod
    def _read_theme_field(path: Path) -> str | None:
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8")).get("theme")
        except (OSError, json.JSONDecodeError):
            return None
