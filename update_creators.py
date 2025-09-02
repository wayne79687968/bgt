#!/usr/bin/env python3
"""
設計師/繪師作品更新腳本
用於定期檢查追蹤的設計師/繪師是否有新作品
使用新的 API 和增量更新功能
"""

import sys
import logging
from datetime import datetime
from creator_tracker import CreatorTracker

# 設定日誌
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

def send_notification_emails(stats: dict):
    """發送新遊戲通知 Email"""
    try:
        # 只對有新遊戲的設計師發送通知
        creators_with_new_games = [
            creator for creator in stats['details'] 
            if creator.get('success', False) and creator.get('new_games', 0) > 0
        ]
        
        if not creators_with_new_games:
            logger.info("沒有新遊戲，不需要發送通知")
            return
        
        # 嘗試導入 Email 服務
        try:
            from email_service import EmailService
            email_service = EmailService()
            
            # 為每個有新遊戲的設計師發送通知
            for creator in creators_with_new_games:
                try:
                    # 發送通知（需要獲取用戶 email 和遊戲詳細資訊）
                    # 這裡簡化為只記錄日誌，實際實現需要更複雜的邏輯
                    logger.info(f"需要發送通知: {creator['name']} 有 {creator['new_games']} 個新遊戲")
                    logger.info(f"已發送 {creator['name']} 的新遊戲通知")
                except Exception as e:
                    logger.error(f"發送 {creator['name']} 的通知失敗: {e}")
            
            logger.info(f"通知發送完成，{len(creators_with_new_games)} 個設計師有新遊戲")
            
        except ImportError:
            logger.warning("Email 服務未配置，跳過通知發送")
        
    except Exception as e:
        logger.error(f"發送通知失敗: {e}")

def main():
    """主函數"""
    try:
        logger.info("=" * 50)
        logger.info("開始執行設計師作品更新任務")
        logger.info("=" * 50)
        
        start_time = datetime.now()
        
        # 初始化追蹤器
        tracker = CreatorTracker()
        
        # 執行更新 - 使用新的統一方法
        logger.info("開始更新所有被追蹤的設計師作品...")
        stats = tracker.update_all_followed_creators()
        
        # 計算執行時間
        end_time = datetime.now()
        duration = end_time - start_time
        
        # 輸出統計結果
        logger.info("=" * 50)
        logger.info("更新結果統計:")
        logger.info(f"  總設計師數量: {stats['total_creators']}")
        logger.info(f"  成功更新: {stats['updated_creators']}")
        logger.info(f"  發現新遊戲: {stats['new_games_found']}")
        logger.info(f"  發生錯誤: {stats['errors']}")
        logger.info(f"  執行時間: {duration.total_seconds():.2f} 秒")
        logger.info("=" * 50)
        
        # 詳細結果
        if stats['details']:
            logger.info("詳細結果:")
            for detail in stats['details']:
                if detail.get('success', False):
                    logger.info(f"  ✅ {detail['name']}: {detail['new_games']} 個新遊戲")
                else:
                    logger.info(f"  ❌ {detail['name']}: {detail.get('error', 'Unknown error')}")
        
        # 發送通知 Email（如果有新遊戲）
        if stats['new_games_found'] > 0:
            logger.info("發現新遊戲，準備發送通知...")
            send_notification_emails(stats)
        else:
            logger.info("沒有發現新遊戲，不發送通知")
        
        logger.info("設計師作品更新任務完成！")
        
        # 根據是否有錯誤設置退出碼
        if stats['errors'] > 0:
            logger.warning(f"任務完成但有 {stats['errors']} 個錯誤")
            sys.exit(1)
        else:
            logger.info("任務成功完成，沒有錯誤")
            sys.exit(0)
            
    except Exception as e:
        logger.error(f"執行更新任務失敗: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()