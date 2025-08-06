#!/usr/bin/env python3
import os
import sys
import time
import subprocess
import logging
import argparse
import json
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
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def fetch_and_generate_report(detail_mode='all', lang='zh-tw', force=False, force_llm_analysis=False):
    """抓取資料並產生報表"""
    # 使用 print 和 logger 雙重記錄，確保排程執行被記錄
    logger.info("🎲 [SCHEDULER] 排程任務開始執行 fetch_and_generate_report")
    logger.info(f"🔧 [SCHEDULER] 執行參數: detail_mode={detail_mode}, lang={lang}, force={force}, force_llm_analysis={force_llm_analysis}")
    logger.info(f"🔧 [SCHEDULER] 當前時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 使用 print 進行即時調試，繞過可能的日誌緩衝問題
    try:
        print("\n" + "="*50)
        print("🎲 [TASK] fetch_and_generate_report 函數開始執行...")
        print(f"🔧 [TASK] 參數: detail_mode={detail_mode}, lang={lang}, force={force}, force_llm_analysis={force_llm_analysis}")
        print(f"🔧 [TASK] 當前工作目錄: {os.getcwd()}")
        print("="*50 + "\n")

        overall_start_time = datetime.now()
        print(f"🕐 [TASK] 開始時間: {overall_start_time.strftime('%Y-%m-%d %H:%M:%S')}")

        # 初始化步驟時間變量
        step1_duration = step2_duration = step3_duration = step4_duration = 0

        # 1. 抓取熱門遊戲榜單
        print("\n--- 📊 步驟 1/4: 抓取熱門遊戲榜單 ---")
        step1_start = datetime.now()
        cmd1 = ['python3', 'fetch_hotgames.py']
        print(f"🚀 [STEP 1] 準備執行命令: {' '.join(cmd1)}")
        print("⏳ [STEP 1] 即將執行 subprocess.run...")

        try:
            result = subprocess.run(cmd1, capture_output=True, text=True, timeout=600)
            print("✅ [STEP 1] subprocess.run 已完成")
        except Exception as e:
            print(f"❌ [STEP 1] subprocess.run 執行失敗: {e}")
            return False

        step1_duration = (datetime.now() - step1_start).total_seconds()
        print(f"📊 [STEP 1] 返回碼: {result.returncode}, 耗時: {step1_duration:.1f}秒")

        if result.stdout:
            print("--- [STEP 1] STDOUT ---")
            for line in result.stdout.split('\n'):
                if line.strip():
                    print(f"  > {line}")
            print("--- [STEP 1] END STDOUT ---")

        if result.stderr:
            print("--- [STEP 1] STDERR ---")
            for line in result.stderr.split('\n'):
                if line.strip():
                    print(f"  > {line}")
            print("--- [STEP 1] END STDERR ---")

        if result.returncode != 0:
            print(f"❌ [STEP 1] 抓取熱門遊戲榜單失敗")
            return False
        print(f"✅ [STEP 1] 熱門遊戲榜單抓取完成 (耗時: {step1_duration:.1f}秒)")

        # 2. 抓取遊戲詳細資訊
        print("\n--- 🎮 步驟 2/4: 抓取遊戲詳細資訊 ---")
        step2_start = datetime.now()
        cmd2 = ['python3', 'fetch_details.py']
        print(f"🚀 [STEP 2] 準備執行命令: {' '.join(cmd2)}")
        print("⏳ [STEP 2] 即將執行 subprocess.run...")

        try:
            result = subprocess.run(cmd2, capture_output=True, text=True, timeout=1200)
            print("✅ [STEP 2] subprocess.run 已完成")
        except Exception as e:
            print(f"❌ [STEP 2] subprocess.run 執行失敗: {e}")
            return False

        step2_duration = (datetime.now() - step2_start).total_seconds()
        print(f"📊 [STEP 2] 返回碼: {result.returncode}, 耗時: {step2_duration:.1f}秒")

        if result.stdout:
            print("--- [STEP 2] STDOUT ---")
            for line in result.stdout.split('\n'):
                if line.strip():
                    print(f"  > {line}")
            print("--- [STEP 2] END STDOUT ---")

        if result.stderr:
            print("--- [STEP 2] STDERR ---")
            for line in result.stderr.split('\n'):
                if line.strip():
                    print(f"  > {line}")
            print("--- [STEP 2] END STDERR ---")

        if result.returncode != 0:
            print(f"❌ [STEP 2] 抓取遊戲詳細資訊失敗")
            return False
        print(f"✅ [STEP 2] 遊戲詳細資訊抓取完成 (耗時: {step2_duration:.1f}秒)")

        # 3. 抓取討論串並翻譯
        print("\n--- 💬 步驟 3/4: 抓取討論串並翻譯 ---")
        step3_start = datetime.now()
        cmd3 = ['python3', 'fetch_bgg_forum_threads.py', '--lang', lang]
        
        # 如果啟用強制 LLM 分析，添加對應參數
        if force_llm_analysis:
            cmd3.append('--force-analysis')
            print("🤖 [STEP 3] 啟用強制 LLM 分析模式")
        
        print(f"🚀 [STEP 3] 準備執行命令: {' '.join(cmd3)}")
        print("⏳ [STEP 3] 即將執行 subprocess.run... (此步驟耗時較長)")

        try:
            result = subprocess.run(cmd3, capture_output=True, text=True, timeout=3600)
            print("✅ [STEP 3] subprocess.run 已完成")
        except Exception as e:
            print(f"❌ [STEP 3] subprocess.run 執行失敗: {e}")
            return False

        step3_duration = (datetime.now() - step3_start).total_seconds()
        print(f"📊 [STEP 3] 返回碼: {result.returncode}, 耗時: {step3_duration:.1f}秒 ({step3_duration/60:.1f}分鐘)")

        if result.stdout:
            print("--- [STEP 3] STDOUT ---")
            for line in result.stdout.split('\n'):
                if line.strip():
                    print(f"  > {line}")
            print("--- [STEP 3] END STDOUT ---")

        if result.stderr:
            print("--- [STEP 3] STDERR ---")
            for line in result.stderr.split('\n'):
                if line.strip():
                    print(f"  > {line}")
            print("--- [STEP 3] END STDERR ---")

        if result.returncode != 0:
            print(f"❌ [STEP 3] 抓取討論串失敗")
            return False
        print(f"✅ [STEP 3] 討論串抓取和翻譯完成 (耗時: {step3_duration:.1f}秒)")

        # 4. 產生報表
        print("\n--- 📝 步驟 4/4: 產生報表 ---")
        step4_start = datetime.now()
        generate_cmd = ['python3', 'generate_report.py', '--lang', lang, '--detail', detail_mode]
        if force:
            generate_cmd.append('--force')
            print("🔄 [STEP 4] 使用強制模式產生報表")

        print(f"🚀 [STEP 4] 準備執行命令: {' '.join(generate_cmd)}")
        print("⏳ [STEP 4] 即將執行 subprocess.run...")

        try:
            result = subprocess.run(generate_cmd, capture_output=True, text=True, timeout=600)
            print("✅ [STEP 4] subprocess.run 已完成")
        except Exception as e:
            print(f"❌ [STEP 4] subprocess.run 執行失敗: {e}")
            return False

        step4_duration = (datetime.now() - step4_start).total_seconds()
        print(f"📊 [STEP 4] 返回碼: {result.returncode}, 耗時: {step4_duration:.1f}秒")

        if result.stdout:
            print("--- [STEP 4] STDOUT ---")
            for line in result.stdout.split('\n'):
                if line.strip():
                    print(f"  > {line}")
            print("--- [STEP 4] END STDOUT ---")

        if result.stderr:
            print("--- [STEP 4] STDERR ---")
            for line in result.stderr.split('\n'):
                if line.strip():
                    print(f"  > {line}")
            print("--- [STEP 4] END STDERR ---")

        if result.returncode != 0:
            print(f"❌ [STEP 4] 產生報表失敗")
            return False

        # 檢查報表檔案是否真的產生了
        print("\n🔍 [TASK] 檢查產生的報表檔案...")
        report_dir = "frontend/public/outputs"
        today = datetime.now().strftime("%Y-%m-%d")
        expected_file = f"report-{today}-{lang}.md"
        expected_path = os.path.join(report_dir, expected_file)

        if os.path.exists(expected_path) and os.path.getsize(expected_path) > 0:
            print(f"✅ [TASK] 成功驗證報表檔案存在且非空: {expected_path}")
        else:
            print(f"❌ [TASK] 報表檔案不存在或為空: {expected_path}")
            return False

        overall_duration = (datetime.now() - overall_start_time).total_seconds()
        print("\n" + "="*50)
        print("🎉 [TASK] fetch_and_generate_report 任務成功完成！")
        print(f"⏱️  總耗時: {overall_duration:.1f}秒 ({overall_duration/60:.1f}分鐘)")
        print(f"📊 各步驟耗時:")
        print(f"  - 步驟1 (熱門榜單): {step1_duration:.1f}秒")
        print(f"  - 步驟2 (遊戲詳情): {step2_duration:.1f}秒")
        print(f"  - 步驟3 (討論翻譯): {step3_duration:.1f}秒")
        print(f"  - 步驟4 (產生報表): {step4_duration:.1f}秒")
        print("="*50)

        return True
    except Exception as e:
        print(f"\n💥 [TASK] fetch_and_generate_report 發生未預期的嚴重錯誤: {e}")
        import traceback
        print(f" traceback: {traceback.format_exc()}")
        return False

def main():
    """主函數"""
    print("=" * 80)
    print("🚀 SCHEDULER.PY 進程開始執行")
    print(f"🕐 啟動時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📁 工作目錄: {os.getcwd()}")
    print("=" * 80)

    parser = argparse.ArgumentParser(description='BGG 報表排程器')
    parser.add_argument('--run-now', action='store_true', help='立即執行報表產生任務')
    parser.add_argument('--detail', choices=['all', 'simple'], default='all', help='報表詳細程度')
    parser.add_argument('--lang', default='zh-tw', help='語言設定')
    parser.add_argument('--force', action='store_true', help='強制產生今日報表')
    parser.add_argument('--force-llm-analysis', action='store_true', help='強制重新進行 LLM 分析')

    args = parser.parse_args()
    print(f"📋 解析的參數: run_now={args.run_now}, detail={args.detail}, lang={args.lang}, force={args.force}, force_llm_analysis={args.force_llm_analysis}")

    # 如果指定 --run-now，立即執行任務
    if args.run_now:
        print("🎯 檢測到 --run-now 參數，即將執行立即任務...")
        print("🚀 立即執行報表產生任務...")

        # 檢查並初始化資料庫
        print("🗃️ [SCHEDULER] 檢查資料庫表格結構...")
        print(f"🗃️ [SCHEDULER] 當前時間: {datetime.now().strftime('%H:%M:%S')}")

        try:
            print("📦 [SCHEDULER] 正在導入數據庫函數...")
            from database import get_db_connection, get_database_config, init_database
            print("✅ [SCHEDULER] 數據庫函數導入成功")

            # 檢查必要的表格是否存在
            required_tables = ['hot_games', 'game_detail', 'forum_threads', 'forum_threads_i18n']
            missing_tables = []

            print(f"📋 [SCHEDULER] 需要檢查 {len(required_tables)} 個必要表格: {required_tables}")
            print("🔗 [SCHEDULER] 正在建立數據庫連接...")

            import time
            check_start_time = time.time()

            with get_db_connection() as conn:
                connection_time = time.time() - check_start_time
                print(f"✅ [SCHEDULER] 數據庫連接建立成功 (耗時: {connection_time:.2f}秒)")

                print("🗃️ [SCHEDULER] 正在創建游標...")
                cursor = conn.cursor()
                print("✅ [SCHEDULER] 游標創建成功")

                print("🔍 [SCHEDULER] 正在獲取數據庫配置...")
                config_start_time = time.time()
                config = get_database_config()
                config_time = time.time() - config_start_time
                print(f"✅ [SCHEDULER] 數據庫配置獲取成功 (耗時: {config_time:.2f}秒): {config['type']}")

                print("🔍 [SCHEDULER] 開始逐個檢查表格...")
                for i, table in enumerate(required_tables, 1):
                    print(f"🔍 [SCHEDULER] 檢查第 {i}/{len(required_tables)} 個表格: {table}")
                    table_check_start = time.time()

                    try:
                        if config['type'] == 'postgresql':
                            print(f"🔍 [SCHEDULER] 執行 PostgreSQL 表格檢查查詢: {table}")
                            cursor.execute("""
                                SELECT EXISTS (
                                    SELECT FROM information_schema.tables
                                    WHERE table_schema = 'public'
                                    AND table_name = %s
                                )
                            """, (table,))
                        else:
                            print(f"🔍 [SCHEDULER] 執行 SQLite 表格檢查查詢: {table}")
                            cursor.execute("""
                                SELECT name FROM sqlite_master
                                WHERE type='table' AND name=?
                            """, (table,))

                        print(f"🔍 [SCHEDULER] 正在獲取查詢結果: {table}")
                        result = cursor.fetchone()
                        table_check_time = time.time() - table_check_start

                        if not result or (config['type'] == 'postgresql' and not result[0]) or (config['type'] == 'sqlite' and not result):
                            print(f"❌ [SCHEDULER] 表格 {table} 不存在 (耗時: {table_check_time:.2f}秒)")
                            missing_tables.append(table)
                        else:
                            print(f"✅ [SCHEDULER] 表格 {table} 存在 (耗時: {table_check_time:.2f}秒)")

                    except Exception as check_error:
                        table_check_time = time.time() - table_check_start if 'table_check_start' in locals() else 0
                        print(f"⚠️ [SCHEDULER] 檢查表格 {table} 時發生錯誤 (耗時: {table_check_time:.2f}秒): {check_error}")
                        print(f"⚠️ [SCHEDULER] 錯誤類型: {type(check_error).__name__}")
                        missing_tables.append(table)

            total_check_time = time.time() - check_start_time
            print(f"📊 [SCHEDULER] 表格檢查完成 (總耗時: {total_check_time:.2f}秒)")
            print(f"📊 [SCHEDULER] 缺少的表格: {missing_tables}")

            if missing_tables:
                print(f"📋 發現缺少的表格: {', '.join(missing_tables)}")
                print("🔧 [SCHEDULER] 開始初始化資料庫...")
                init_start_time = time.time()
                init_database()
                init_time = time.time() - init_start_time
                print(f"✅ [SCHEDULER] 資料庫初始化完成 (耗時: {init_time:.2f}秒)")
            else:
                print("✅ 所有必要的資料庫表格都已存在")

        except Exception as e:
            print(f"❌ [SCHEDULER] 資料庫檢查/初始化失敗: {e}")
            print(f"❌ [SCHEDULER] 錯誤類型: {type(e).__name__}")
            import traceback
            print(f"❌ [SCHEDULER] 錯誤詳情: {traceback.format_exc()}")
            return

        print("🎯 [SCHEDULER] 數據庫檢查完成，開始執行報表生成任務...")
        print(f"🎯 [SCHEDULER] 任務參數: detail={args.detail}, lang={args.lang}, force={args.force}")

        task_start_time = time.time()
        success = fetch_and_generate_report(args.detail, args.lang, args.force, args.force_llm_analysis)
        task_time = time.time() - task_start_time

        if success:
            print(f"✅ [SCHEDULER] 任務執行成功 (總耗時: {task_time:.2f}秒)")
        else:
            print(f"❌ [SCHEDULER] 任務執行失敗 (總耗時: {task_time:.2f}秒)")
        return

    # 以下為排程器邏輯，保持使用 logger
    logger.info("🚀 啟動 BGG 報表排程器...")

    # 檢查並初始化資料庫
    logger.info("🗃️ 檢查資料庫表格結構...")
    try:
        from database import get_db_connection, get_database_config

        # 檢查必要的表格是否存在
        required_tables = ['hot_games', 'game_detail', 'forum_threads', 'forum_threads_i18n']
        missing_tables = []

        with get_db_connection() as conn:
            cursor = conn.cursor()
            config = get_database_config()

            for table in required_tables:
                try:
                    if config['type'] == 'postgresql':
                        cursor.execute("""
                            SELECT EXISTS (
                                SELECT FROM information_schema.tables
                                WHERE table_schema = 'public'
                                AND table_name = %s
                            )
                        """, (table,))
                    else:
                        cursor.execute("""
                            SELECT name FROM sqlite_master
                            WHERE type='table' AND name=?
                        """, (table,))

                    result = cursor.fetchone()
                    if not result or (config['type'] == 'postgresql' and not result[0]) or (config['type'] == 'sqlite' and not result):
                        missing_tables.append(table)
                except Exception as check_error:
                    logger.warning(f"⚠️ 檢查表格 {table} 時發生錯誤: {check_error}")
                    missing_tables.append(table)

        if missing_tables:
            logger.info(f"📋 發現缺少的表格: {', '.join(missing_tables)}")
            logger.info("🔧 開始初始化資料庫...")
            init_database()
            logger.info("✅ 資料庫初始化完成")
        else:
            logger.info("✅ 所有必要的資料庫表格都已存在")

    except Exception as e:
        logger.error(f"❌ 資料庫檢查/初始化失敗: {e}")
        return

    # 設定排程器
    timezone = pytz.timezone(os.getenv('TZ', 'Asia/Taipei'))
    scheduler = BlockingScheduler(timezone=timezone)

    # 讀取排程設定
    schedule_file = 'schedule_settings.json'
    current_settings = {'hour': None, 'minute': None}
    last_modified = 0
    
    def get_schedule_settings():
        """讀取排程設定檔"""
        default_hour = int(os.getenv('SCHEDULE_HOUR', 23))
        default_minute = int(os.getenv('SCHEDULE_MINUTE', 0))
        
        try:
            if os.path.exists(schedule_file):
                with open(schedule_file, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
                hour = settings.get('hour', default_hour)
                minute = settings.get('minute', default_minute)
                return hour, minute
            else:
                return default_hour, default_minute
        except Exception as e:
            logger.warning(f"⚠️ 讀取排程設定失敗，使用預設值: {e}")
            return default_hour, default_minute

    def check_and_update_schedule():
        """檢查設定檔案是否有更新，如有則更新排程"""
        nonlocal last_modified, current_settings
        
        try:
            logger.debug(f"🔍 檢查排程設定檔案: {schedule_file}")
            if os.path.exists(schedule_file):
                file_modified = os.path.getmtime(schedule_file)
                logger.debug(f"🔍 檔案修改時間: {file_modified}, 上次記錄: {last_modified}")
                
                if file_modified > last_modified:
                    hour, minute = get_schedule_settings()
                    logger.info(f"🔍 讀取到設定: {hour:02d}:{minute:02d}, 目前設定: {current_settings['hour']:02d}:{current_settings['minute']:02d}")
                    
                    if current_settings['hour'] != hour or current_settings['minute'] != minute:
                        logger.info(f"📅 偵測到排程設定變更: {hour:02d}:{minute:02d}")
                        
                        # 先檢查舊排程是否存在
                        old_job = scheduler.get_job('daily_report')
                        if old_job:
                            logger.info(f"🗑️ 移除舊排程: {old_job.next_run_time}")
                            scheduler.remove_job('daily_report')
                        else:
                            logger.warning("⚠️ 找不到舊的排程任務")
                        
                        # 添加新的排程
                        logger.info(f"➕ 添加新排程: {hour:02d}:{minute:02d}")
                        scheduler.add_job(
                            scheduled_task,
                            trigger=CronTrigger(hour=hour, minute=minute),
                            id='daily_report',
                            name='每日BGG報表產生任務',
                            replace_existing=True,
                            misfire_grace_time=3600  # 1 小時
                        )
                        
                        current_settings['hour'] = hour
                        current_settings['minute'] = minute
                        last_modified = file_modified
                        
                        # 顯示下次執行時間
                        job = scheduler.get_job('daily_report')
                        if job:
                            logger.info(f"✅ 排程已更新，下次執行時間: {job.next_run_time}")
                        else:
                            logger.error("❌ 新排程添加失敗")
                        
                        # 列出所有活動的排程任務
                        jobs = scheduler.get_jobs()
                        logger.info(f"📋 目前活動的排程任務數量: {len(jobs)}")
                        for job in jobs:
                            logger.info(f"  - {job.id}: {job.name}, 下次執行: {job.next_run_time}")
                        
                        return True
                    else:
                        last_modified = file_modified  # 更新時間戳，即使設定沒變
                        
            else:
                logger.warning(f"⚠️ 排程設定檔案不存在: {schedule_file}")
                
        except Exception as e:
            logger.error(f"❌ 檢查排程設定時發生錯誤: {e}")
            import traceback
            logger.error(f"錯誤詳情: {traceback.format_exc()}")
        
        return False

    # 初始設定
    schedule_hour, schedule_minute = get_schedule_settings()
    current_settings['hour'] = schedule_hour
    current_settings['minute'] = schedule_minute
    if os.path.exists(schedule_file):
        last_modified = os.path.getmtime(schedule_file)
        logger.info(f"📅 初始設定檔案修改時間: {last_modified}")
    else:
        logger.info("📅 未找到設定檔案，使用預設值")

    logger.info(f"⏰ 初始排程設定時間: {schedule_hour:02d}:{schedule_minute:02d}")

    # 定義排程任務函數
    def scheduled_task():
        """排程任務執行函數"""
        logger.info("🚀 [SCHEDULER] 定時任務被觸發")
        logger.info(f"🕐 [SCHEDULER] 觸發時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        try:
            result = fetch_and_generate_report(args.detail, args.lang, False, False)
            if result:
                logger.info("✅ [SCHEDULER] 排程任務執行完成")
            else:
                logger.error("❌ [SCHEDULER] 排程任務執行失敗")
            return result
        except Exception as e:
            logger.error(f"💥 [SCHEDULER] 排程任務執行異常: {e}")
            import traceback
            logger.error(f"異常詳情: {traceback.format_exc()}")
            return False

    # 添加每日任務
    logger.info("➕ 添加初始排程任務...")
    scheduler.add_job(
        scheduled_task,
        trigger=CronTrigger(hour=schedule_hour, minute=schedule_minute),
        id='daily_report',
        name='每日BGG報表產生任務',
        replace_existing=True,
        misfire_grace_time=3600  # 1 小時
    )
    
    # 添加設定檢查任務（每分鐘檢查一次）
    logger.info("➕ 添加排程檢查任務...")
    scheduler.add_job(
        check_and_update_schedule,
        trigger=CronTrigger(second=0),  # 每分鐘的第0秒執行
        id='schedule_checker',
        name='排程設定檢查任務',
        replace_existing=True
    )

    logger.info("🔄 排程器開始運行，等待執行時間...")

    try:
        scheduler.start()
        
        # 顯示所有排程任務的下次執行時間
        jobs = scheduler.get_jobs()
        logger.info(f"📋 已註冊的排程任務數量: {len(jobs)}")
        for job in jobs:
            logger.info(f"  - {job.id}: {job.name}, 下次執行: {job.next_run_time}")
        
        # 保持程式運行
        import signal
        
        def signal_handler(signum, frame):
            logger.info(f"⏹️  收到信號 {signum}，正在停止排程器...")
            scheduler.shutdown(wait=True)
            sys.exit(0)
        
        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)
        
        # 無限循環保持程式運行，但允許優雅停止
        while True:
            time.sleep(1)
            
    except KeyboardInterrupt:
        logger.info("⏹️  排程器已停止 (KeyboardInterrupt)")
        scheduler.shutdown(wait=True)
    except Exception as e:
        logger.error(f"❌ 排程器運行時發生錯誤: {e}")
        scheduler.shutdown(wait=True)
        raise

if __name__ == '__main__':
    main()