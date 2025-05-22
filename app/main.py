from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import logging
from routes import audio, video, transcript

import uvicorn

# ロギングの設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# FastAPIアプリケーションの初期化
app = FastAPI(
    title="YouTube Audio/Video/Transcript Extractor",
    description="Extract high quality audio, video, and transcripts from YouTube videos",
    version="1.1.0"
)

# CORSミドルウェアの設定
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 本番環境では適切に制限する
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# リクエストモデル
class AudioExtractionRequest(BaseModel):
    url: str

# ルートの登録
app.include_router(audio.router, prefix="/api/v1")  
app.include_router(video.router, prefix="/api/v1")
app.include_router(transcript.router, prefix="/api/v1")

# ヘルスチェックエンドポイント
@app.get("/health")
async def health_check():
    return {"status": "healthy"}

# ルーターのインポートと登録は後で追加

# タイムアウト設定の追加
if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=7783,
        timeout_keep_alive=6000,  # 10分
    )