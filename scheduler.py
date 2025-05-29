#!/usr/bin/env python3
import os
import subprocess
import logging
from datetime import datetime
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv
import pytz

# 載入環境變數
load_dotenv()

# 設定日誌
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def fetch_and_generate_report():
    """抓取資料並產生報表"""
    try:
        logger.info("🎲 開始執行每日報表產生任務...")
        start_time = datetime.now()

        # 1. 抓取熱門遊戲榜單
        logger.info("📊 步驟 1/4: 抓取熱門遊戲榜單...")
        result = subprocess.run(['python3', 'fetch_bgg_hot_games.py'],
                              capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            logger.error(f"❌ 抓取熱門遊戲榜單失敗: {result.stderr}")
            return False
        logger.info("✅ 熱門遊戲榜單抓取完成")

        # 2. 抓取遊戲詳細資訊
        logger.info("🎮 步驟 2/4: 抓取遊戲詳細資訊...")
        result = subprocess.run(['python3', 'fetch_bgg_game_details.py'],
                              capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            logger.error(f"❌ 抓取遊戲詳細資訊失敗: {result.stderr}")
            return False
        logger.info("✅ 遊戲詳細資訊抓取完成")

        # 3. 抓取討論串並翻譯
        logger.info("💬 步驟 3/4: 抓取討論串並翻譯...")
        result = subprocess.run(['python3', 'fetch_bgg_forum_threads.py', '--lang', 'zh-tw'],
                              capture_output=True, text=True, timeout=1800)
        if result.returncode != 0:
            logger.error(f"❌ 抓取討論串失敗: {result.stderr}")
            return False
        logger.info("✅ 討論串抓取和翻譯完成")

        # 4. 產生報表
        logger.info("📝 步驟 4/4: 產生報表...")
        result = subprocess.run(['python3', 'generate_report.py', '--lang', 'zh-tw', '--detail', 'all'],
                              capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            logger.error(f"❌ 產生報表失敗: {result.stderr}")
            return False

        end_time = datetime.now()
        duration = end_time - start_time
        logger.info(f"🎉 每日報表產生任務完成！耗時: {duration}")
        return True

    except subprocess.TimeoutExpired:
        logger.error("⏰ 任務執行超時")
        return False
    except Exception as e:
        logger.error(f"💥 任務執行異常: {e}")
        return False

def main():
    """主程式"""
    logger.info("🚀 啟動 BGG 報表排程器...")

    # 設定時區
    timezone = pytz.timezone(os.getenv('TZ', 'Asia/Taipei'))
    logger.info(f"⏰ 時區設定: {timezone}")

    scheduler = BlockingScheduler(timezone=timezone)

    # 每天早上 9:00 執行
    scheduler.add_job(
        fetch_and_generate_report,
        CronTrigger(hour=9, minute=0, timezone=timezone),
        id='daily_report',
        name='每日 BGG 報表產生',
        replace_existing=True
    )

    logger.info("📅 排程器已設定：每天早上 9:00 (台北時間) 執行報表產生")
    logger.info("🔄 排程器開始運行，等待執行時間...")

    # 顯示下次執行時間
    next_run = scheduler.get_job('daily_report').next_run_time
    logger.info(f"⏭️  下次執行時間: {next_run}")

    try:
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("⏹️  排程器已停止")
        scheduler.shutdown()

if __name__ == '__main__':
    main()