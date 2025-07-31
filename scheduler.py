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
        logger.info(f"🔧 參數: detail_mode={detail_mode}, lang={lang}, force={force}")
        logger.info(f"🔧 當前工作目錄: {os.getcwd()}")

        start_time = datetime.now()
        logger.info(f"🕐 開始時間: {start_time}")

        # 1. 抓取熱門遊戲榜單
        logger.info("📊 步驟 1/4: 抓取熱門遊戲榜單...")
        cmd1 = ['python3', 'fetch_hotgames.py']
        logger.info(f"🚀 執行命令: {' '.join(cmd1)}")

        result = subprocess.run(cmd1, capture_output=True, text=True, timeout=300)
        logger.info(f"📊 步驟 1 返回碼: {result.returncode}")

        if result.stdout:
            for line in result.stdout.split('\n'):
                if line.strip():
                    logger.info(f"  步驟1 STDOUT: {line}")

        if result.stderr:
            for line in result.stderr.split('\n'):
                if line.strip():
                    logger.info(f"  步驟1 STDERR: {line}")

        if result.returncode != 0:
            logger.error(f"❌ 抓取熱門遊戲榜單失敗: {result.stderr}")
            return False
        logger.info("✅ 熱門遊戲榜單抓取完成")

        # 2. 抓取遊戲詳細資訊
        logger.info("🎮 步驟 2/4: 抓取遊戲詳細資訊...")
        cmd2 = ['python3', 'fetch_details.py']
        logger.info(f"🚀 執行命令: {' '.join(cmd2)}")

        result = subprocess.run(cmd2, capture_output=True, text=True, timeout=600)
        logger.info(f"📊 步驟 2 返回碼: {result.returncode}")

        if result.stdout:
            for line in result.stdout.split('\n'):
                if line.strip():
                    logger.info(f"  步驟2 STDOUT: {line}")

        if result.stderr:
            for line in result.stderr.split('\n'):
                if line.strip():
                    logger.info(f"  步驟2 STDERR: {line}")

        if result.returncode != 0:
            logger.error(f"❌ 抓取遊戲詳細資訊失敗: {result.stderr}")
            return False
        logger.info("✅ 遊戲詳細資訊抓取完成")

        # 3. 抓取討論串並翻譯
        logger.info("💬 步驟 3/4: 抓取討論串並翻譯...")
        cmd3 = ['python3', 'fetch_bgg_forum_threads.py', '--lang', lang]
        logger.info(f"🚀 執行命令: {' '.join(cmd3)}")

        result = subprocess.run(cmd3, capture_output=True, text=True, timeout=1800)
        logger.info(f"📊 步驟 3 返回碼: {result.returncode}")

        if result.stdout:
            for line in result.stdout.split('\n'):
                if line.strip():
                    logger.info(f"  步驟3 STDOUT: {line}")

        if result.stderr:
            for line in result.stderr.split('\n'):
                if line.strip():
                    logger.info(f"  步驟3 STDERR: {line}")

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

        logger.info(f"🚀 執行命令: {' '.join(generate_cmd)}")

        result = subprocess.run(generate_cmd, capture_output=True, text=True, timeout=300)
        logger.info(f"📊 步驟 4 返回碼: {result.returncode}")

        if result.stdout:
            for line in result.stdout.split('\n'):
                if line.strip():
                    logger.info(f"  步驟4 STDOUT: {line}")

        if result.stderr:
            for line in result.stderr.split('\n'):
                if line.strip():
                    logger.info(f"  步驟4 STDERR: {line}")

        if result.returncode != 0:
            logger.error(f"❌ 產生報表失敗: {result.stderr}")
            return False

        # 檢查報表檔案是否真的產生了
        logger.info("🔍 檢查產生的報表檔案...")
        report_dir = "frontend/public/outputs"
        today = datetime.now().strftime("%Y-%m-%d")
        expected_file = f"report-{today}-{lang}.md"
        expected_path = os.path.join(report_dir, expected_file)

        logger.info(f"🔍 檢查預期檔案: {expected_path}")

        if os.path.exists(expected_path):
            file_size = os.path.getsize(expected_path)
            file_mtime = os.path.getmtime(expected_path)
            mtime_str = datetime.fromtimestamp(file_mtime).strftime('%Y-%m-%d %H:%M:%S')
            logger.info(f"✅ 發現報表檔案: {expected_file} ({file_size} bytes, 修改時間: {mtime_str})")

            # 讀取檔案的前幾行來驗證內容
            try:
                with open(expected_path, 'r', encoding='utf-8') as f:
                    first_lines = [f.readline().strip() for _ in range(3)]
                logger.info("📝 檔案內容預覽:")
                for i, line in enumerate(first_lines, 1):
                    if line:
                        logger.info(f"  第{i}行: {line[:100]}...")
            except Exception as e:
                logger.error(f"❌ 讀取檔案內容失敗: {e}")
        else:
            logger.error(f"❌ 預期的報表檔案不存在: {expected_path}")

            # 列出目錄中的所有檔案
            if os.path.exists(report_dir):
                files = os.listdir(report_dir)
                logger.info(f"📂 報表目錄中現有檔案 ({len(files)} 個):")
                for f in sorted(files, reverse=True)[:10]:
                    file_path = os.path.join(report_dir, f)
                    file_size = os.path.getsize(file_path)
                    file_mtime = os.path.getmtime(file_path)
                    mtime_str = datetime.fromtimestamp(file_mtime).strftime('%Y-%m-%d %H:%M:%S')
                    logger.info(f"  📄 {f} ({file_size} bytes, {mtime_str})")
            else:
                logger.error(f"❌ 報表目錄不存在: {report_dir}")

        end_time = datetime.now()
        duration = end_time - start_time
        logger.info(f"🎉 每日報表產生任務完成！耗時: {duration}")
        logger.info(f"🕐 結束時間: {end_time}")
        return True

    except subprocess.TimeoutExpired:
        logger.error("⏰ 任務執行超時")
        return False
    except Exception as e:
        logger.error(f"💥 任務執行異常: {e}")
        import traceback
        logger.error(f"💥 異常堆疊: {traceback.format_exc()}")
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