#!/usr/bin/env python3
from database import get_db_connection, get_database_config, execute_query

def clean_duplicate_comments():
    with get_db_connection() as conn:
        cursor = conn.cursor()

        print("🔍 查找重複評論...")

        # 找出所有重複的評論組（只比較 objectid 和 comment）
        cursor.execute("""
            SELECT objectid, comment, COUNT(*) as count
            FROM game_comments
            GROUP BY objectid, comment
            HAVING COUNT(*) > 1
        """)

        duplicates = cursor.fetchall()

        if not duplicates:
            print("✅ 沒有找到重複評論")
            return

        print(f"📊 找到 {len(duplicates)} 組重複評論")

        total_deleted = 0
        for objectid, comment, count in duplicates:
            print(f"🎮 遊戲 {objectid}: {comment[:50]}... (重複 {count} 次)")

            # 找出這組重複評論的所有 ID
            execute_query(cursor, """
                SELECT id FROM game_comments
                WHERE objectid = ? AND comment = ?
                ORDER BY id
            """, (objectid, comment))

            ids = [row[0] for row in cursor.fetchall()]

            # 保留第一個，刪除其他的
            ids_to_delete = ids[1:]

            for delete_id in ids_to_delete:
                # 先刪除相關的翻譯記錄
                execute_query(cursor, "DELETE FROM game_comments_i18n WHERE comment_id = ?", (delete_id,))
                # 再刪除評論本身
                execute_query(cursor, "DELETE FROM game_comments WHERE id = ?", (delete_id,))

            total_deleted += len(ids_to_delete)
            print(f"  🗑️ 刪除了 {len(ids_to_delete)} 個重複項，保留 ID {ids[0]}")

        conn.commit()
        print(f"✅ 清理完成，總共刪除了 {total_deleted} 個重複評論")

if __name__ == "__main__":
    clean_duplicate_comments()