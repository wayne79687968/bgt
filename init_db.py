#!/usr/bin/env python3
from database import init_database

if __name__ == '__main__':
    print("🗃️ 開始初始化資料庫...")
    init_database()
    print("✅ 資料庫初始化完成")

    # 現在所有表的建立都在 database.py 的 init_database() 中處理

