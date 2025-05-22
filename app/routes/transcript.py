from fastapi import APIRouter, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel, HttpUrl
import logging
import asyncio
import os
import tempfile
import re
from services.transcript_service import TranscriptService
from utils.cleanup import cleanup_temp_files

logger = logging.getLogger(__name__)

router = APIRouter()

class TranscriptRequest(BaseModel):
    url: HttpUrl

class TranscriptResponse(BaseModel):
    transcript: str
    title: str
    url: str
    language: str
    duration: str
    subtitle_type: str  # "auto" or "manual"

@router.post("/extract-transcript", response_model=TranscriptResponse)
async def extract_transcript(
    request: TranscriptRequest,
    background_tasks: BackgroundTasks
):
    """
    YouTubeの動画からトランスクリプトを抽出し、Claude向けの読みやすい形式で返却
    """
    try:
        logger.info(f"トランスクリプト抽出リクエスト: {request.url}")
        
        # トランスクリプトサービスを初期化
        transcript_service = TranscriptService()
        
        # トランスクリプトを抽出
        result = await transcript_service.extract_transcript(str(request.url))
        
        # 一時ファイルのクリーンアップをバックグラウンドタスクに追加
        background_tasks.add_task(
            cleanup_temp_files, 
            transcript_service.temp_dir
        )
        
        logger.info(f"トランスクリプト抽出完了: {result['title']}")
        
        return TranscriptResponse(
            transcript=result['formatted_transcript'],
            title=result['title'],
            url=str(request.url),
            language=result['language'],
            duration=result['duration'],
            subtitle_type=result['subtitle_type']
        )
        
    except ValueError as e:
        logger.error(f"バリデーションエラー: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    
    except FileNotFoundError as e:
        logger.error(f"字幕ファイルが見つかりません: {str(e)}")
        raise HTTPException(
            status_code=404, 
            detail="この動画には字幕が利用できません"
        )
    
    except Exception as e:
        logger.error(f"トランスクリプト抽出エラー: {str(e)}")
        raise HTTPException(
            status_code=500, 
            detail="トランスクリプトの抽出に失敗しました"
        )

@router.get("/transcript/health")
async def transcript_health_check():
    """トランスクリプト機能のヘルスチェック"""
    try:
        # yt-dlpが利用可能かチェック
        import subprocess
        result = subprocess.run(
            ["yt-dlp", "--version"], 
            capture_output=True, 
            text=True, 
            timeout=10
        )
        
        if result.returncode == 0:
            return {
                "status": "healthy",
                "yt_dlp_version": result.stdout.strip(),
                "message": "トランスクリプト機能は正常に動作しています"
            }
        else:
            raise Exception("yt-dlp command failed")
            
    except Exception as e:
        logger.error(f"ヘルスチェック失敗: {str(e)}")
        raise HTTPException(
            status_code=503,
            detail="トランスクリプト機能が利用できません"
        )