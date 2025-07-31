#!/usr/bin/env python3
import os
import subprocess
import logging
import argparse
from datetime import datetime
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv
import pytz
from database import init_database

# 載入環境變數
load_dotenv()

# 設定日誌
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def fetch_and_generate_report(detail_mode='all', lang='zh-tw', force=False):
    """抓取資料並產生報表"""
    try:
        logger.info("🎲 開始執行每日報表產生任務...")
        start_time = datetime.now()

        # 1. 抓取熱門遊戲榜單
        logger.info("📊 步驟 1/4: 抓取熱門遊戲榜單...")
        result = subprocess.run(['python3', 'fetch_hotgames.py'],
                              capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            logger.error(f"❌ 抓取熱門遊戲榜單失敗: {result.stderr}")
            return False
        logger.info("✅ 熱門遊戲榜單抓取完成")

        # 2. 抓取遊戲詳細資訊
        logger.info("🎮 步驟 2/4: 抓取遊戲詳細資訊...")
        result = subprocess.run(['python3', 'fetch_details.py'],
                              capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            logger.error(f"❌ 抓取遊戲詳細資訊失敗: {result.stderr}")
            return False
        logger.info("✅ 遊戲詳細資訊抓取完成")

        # 3. 抓取討論串並翻譯
        logger.info("💬 步驟 3/4: 抓取討論串並翻譯...")
        result = subprocess.run(['python3', 'fetch_bgg_forum_threads.py', '--lang', lang],
                              capture_output=True, text=True, timeout=1800)
        if result.returncode != 0:
            logger.error(f"❌ 抓取討論串失敗: {result.stderr}")
            return False
        logger.info("✅ 討論串抓取和翻譯完成")

        # 4. 產生報表
        logger.info("📝 步驟 4/4: 產生報表...")
        generate_cmd = ['python3', 'generate_report.py', '--lang', lang, '--detail', detail_mode]
        if force:
            generate_cmd.append('--force')
            logger.info("🔄 使用強制模式產生報表")

        result = subprocess.run(generate_cmd, capture_output=True, text=True, timeout=300)
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
    # 解析命令行參數
    parser = argparse.ArgumentParser(description='BGG 報表排程器')
    parser.add_argument('--run-now', action='store_true',
                       help='立即執行報表產生任務（不啟動排程器）')
    parser.add_argument('--detail', choices=['all', 'up', 'new', 'up_and_new'], default='new',
                       help='詳細資料顯示模式：all=全部, up=只顯示排名上升, new=只顯示新進榜, up_and_new=排名上升+新進榜')
    parser.add_argument('--lang', choices=['zh-tw', 'en'], default='zh-tw',
                       help='報表語言')
    parser.add_argument('--force', action='store_true',
                       help='強制產生今日報表，即使已存在')

    args = parser.parse_args()

    # 如果指定 --run-now，立即執行任務
    if args.run_now:
        logger.info("🚀 立即執行報表產生任務...")

        # 確保資料庫已初始化
        logger.info("🗃️ 確保資料庫已初始化...")
        try:
            init_database()
            logger.info("✅ 資料庫初始化完成")
        except Exception as e:
            logger.error(f"❌ 資料庫初始化失敗: {e}")
            return

        success = fetch_and_generate_report(args.detail, args.lang, args.force)
        if success:
            logger.info("✅ 任務執行成功")
        else:
            logger.error("❌ 任務執行失敗")
        return

    logger.info("🚀 啟動 BGG 報表排程器...")

    # 確保資料庫已初始化
    logger.info("🗃️ 確保資料庫已初始化...")
    try:
        init_database()
        logger.info("✅ 資料庫初始化完成")
    except Exception as e:
        logger.error(f"❌ 資料庫初始化失敗: {e}")
        return

    # 設定時區
    timezone = pytz.timezone(os.getenv('TZ', 'Asia/Taipei'))
    logger.info(f"⏰ 時區設定: {timezone}")

    scheduler = BlockingScheduler(timezone=timezone)

    # 每天早上 8:00 執行
    scheduler.add_job(
        lambda: fetch_and_generate_report(args.detail, args.lang),
        CronTrigger(hour=8, minute=0, timezone=timezone),
        id='daily_report',
        name='每日 BGG 報表產生',
        replace_existing=True
    )

    logger.info("📅 排程器已設定：每天早上 8:00 (台北時間) 執行報表產生")
    logger.info("🔄 排程器開始運行，等待執行時間...")

    try:
        scheduler.start()
        # 顯示下次執行時間（在 scheduler.start() 之後）
        job = scheduler.get_job('daily_report')
        if job:
            logger.info(f"⏭️  下次執行時間: {job.next_run_time}")
    except KeyboardInterrupt:
        logger.info("⏹️  排程器已停止")
        scheduler.shutdown()

if __name__ == '__main__':
    main()