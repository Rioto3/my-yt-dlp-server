import os
import shutil
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

async def cleanup_temp_files(temp_dir: str):
    """
    一時ディレクトリとその中のファイルを削除
    """
    try:
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
            logger.info(f"一時ファイルを削除しました: {temp_dir}")
    except Exception as e:
        logger.error(f"一時ファイルの削除に失敗: {str(e)}")

def cleanup_old_temp_files(base_temp_dir: str = "/tmp", max_age_hours: int = 24):
    """
    古い一時ファイルを定期的にクリーンアップ
    """
    try:
        import time
        current_time = time.time()
        max_age_seconds = max_age_hours * 3600
        
        for item in Path(base_temp_dir).glob("yt_transcript_*"):
            if item.is_dir():
                # ディレクトリの作成時間をチェック
                dir_age = current_time - item.stat().st_ctime
                if dir_age > max_age_seconds:
                    shutil.rmtree(str(item))
                    logger.info(f"古い一時ディレクトリを削除: {item}")
                    
    except Exception as e:
        logger.error(f"古い一時ファイルのクリーンアップエラー: {str(e)}")