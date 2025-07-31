#!/usr/bin/env python3
from database import get_db_connection, get_database_config

def execute_query(cursor, query, params):
    """執行相容性查詢"""
    config = get_database_config()
    if config['type'] == 'postgresql':
        query_pg = query.replace('?', '%s')
        cursor.execute(query_pg, params)
    else:
        cursor.execute(query, params)

def clean_duplicate_comments():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        print("🔍 查找重複評論...")

        # 找出所有重複的評論組（只比較 objectid 和 comment）
        cursor.execute("""
            SELECT objectid, comment, COUNT(*) as count
            FROM game_comments
            WHERE comment != ''
            GROUP BY objectid, comment
            HAVING COUNT(*) > 1
            ORDER BY count DESC
        """)

        duplicates = cursor.fetchall()
        print(f"發現 {len(duplicates)} 組重複評論")

        total_deleted = 0

        for objectid, comment, count in duplicates:
            print(f"處理重複評論：objectid={objectid}, count={count}")

            # 找出這組重複評論的所有 id，按 id 排序
            execute_query(cursor, """
                SELECT id FROM game_comments
                WHERE objectid = ? AND comment = ?
                ORDER BY id
            """, (objectid, comment))

            ids = [row[0] for row in cursor.fetchall()]

            if len(ids) > 1:
                # 保留第一個（id 最小的），刪除其他的
                keep_id = ids[0]
                delete_ids = ids[1:]

                print(f"  保留 id={keep_id}，刪除 {len(delete_ids)} 個重複記錄")

                # 刪除重複的評論
                for delete_id in delete_ids:
                    execute_query(cursor, "DELETE FROM game_comments WHERE id = ?", (delete_id,))
                    # 同時刪除對應的翻譯記錄
                    execute_query(cursor, "DELETE FROM game_comments_i18n WHERE comment_id = ?", (delete_id,))
                    total_deleted += 1

        conn.commit()

        print(f"✅ 清理完成，共刪除 {total_deleted} 個重複評論")

if __name__ == "__main__":
    clean_duplicate_comments()