#!/usr/bin/env python3
"""
通用工具：路徑確保與日誌設定
"""

import logging
import os
from typing import Iterable


def ensure_paths(paths: Iterable[str]) -> None:
    """確保多個目錄存在。

    Args:
        paths: 要確保存在的目錄清單
    """
    for p in paths:
        if not p:
            continue
        try:
            os.makedirs(p, exist_ok=True)
        except Exception:
            # 保守處理，避免干擾主要流程
            pass


def setup_logging(level: int = logging.INFO) -> None:
    """設定統一日誌格式（若尚未設定）。"""
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(
            level=level,
            format='%(asctime)s - %(levelname)s - %(name)s - %(message)s'
        )

