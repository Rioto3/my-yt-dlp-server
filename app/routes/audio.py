from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, HttpUrl
from services.extractor import AudioExtractor
from utils.file_handler import cleanup_temp_file
import logging
from urllib.parse import quote, urlparse, parse_qs
import os
import zipfile
from fastapi import BackgroundTasks
import shutil
from mutagen.id3 import ID3
import asyncio  # Add this line to import the asyncio module


logger = logging.getLogger(__name__)
router = APIRouter()

class AudioExtractionRequest(BaseModel):
    url: HttpUrl


@router.post("/extract-audio")
async def extract_audio(request: AudioExtractionRequest):
    try:
        extractor = AudioExtractor()
        result = await extractor.extract(str(request.url))
        
        # ファイル名を適切にエンコード
        filename = result["filename"]
        encoded_filename = quote(filename)
        
        # 重要: ファイルをコピーして一時ディレクトリに保存
        temp_dir = "download_cache"
        os.makedirs(temp_dir, exist_ok=True)
        
        # 一意のファイル名を生成
        import uuid
        cache_filename = f"{uuid.uuid4().hex}.mp3"
        cache_path = os.path.join(temp_dir, cache_filename)
        
        # ファイルをコピー
        import shutil
        shutil.copy2(result["file_path"], cache_path)
        logger.info(f"Copied file to cache: {cache_path}")
        
        # 元のファイルはすぐに削除
        await cleanup_temp_file(result["file_path"])
        
        # キャッシュからファイルを送信
        response = FileResponse(
            path=cache_path,
            media_type="audio/mpeg",
            filename=filename
        )
        
        # Content-Dispositionヘッダーを明示的に設定
        response.headers["Content-Disposition"] = f'attachment; filename="{encoded_filename}"; filename*=UTF-8\'\'{encoded_filename}'
        
        # ダウンロード完了後に遅延してクリーンアップ (30秒後)
        async def delayed_cleanup():
            await asyncio.sleep(30)  # 30秒待機
            await cleanup_temp_file(cache_path)
            logger.info(f"Cleaned up cached file after delay: {cache_path}")
        
        # バックグラウンドタスクとして実行
        asyncio.create_task(delayed_cleanup())
        
        return response

    except Exception as e:
        logger.error(f"Error processing request: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/extract-album")
async def extract_album(request: AudioExtractionRequest):
    try:
        parsed_url = urlparse(str(request.url))
        query_params = parse_qs(parsed_url.query)
        playlist_id = query_params.get('list', [None])[0]

        if playlist_id:
            playlist_url = f"https://www.youtube.com/playlist?list={playlist_id}"
            logger.info(f"Found playlist URL: {playlist_url}")

            extractor = AudioExtractor()
            playlist_info = await extractor.get_playlist_info(playlist_url)
            
            # アルバムディレクトリの作成
            album_title = playlist_info.get('title', 'Unknown_Album')
            safe_album_title = "".join(c for c in album_title if c.isalnum() or c in (' ', '-', '_')).rstrip()
            album_dir = os.path.join(extractor.temp_dir, safe_album_title)
            os.makedirs(album_dir, exist_ok=True)
            logger.info(f"Created album directory: {album_dir}")

            total_videos = len(playlist_info.get('entries', []))
            logger.info(f"Processing {total_videos} videos for album: {album_title}")

            # ファイルの保存を確認するためのログを追加
            saved_files = []

            # 各動画を処理
            for i, entry in enumerate(playlist_info.get('entries', []), 1):
                video_id = entry.get('id')
                if video_id:
                    video_url = f"https://www.youtube.com/watch?v={video_id}"
                    try:
                        # album_dir を渡して、そこにファイルを保存
                        result = await extractor.extract(video_url, output_dir=album_dir)
                        saved_files.append(result["file_path"])
                        logger.info(f"Saved file: {result['file_path']}")
                    except Exception as e:
                        logger.error(f"Error processing video {video_id}: {str(e)}")

            # 保存されたファイルの確認
            files_in_dir = os.listdir(album_dir)
            logger.info(f"Files in album directory before ZIP: {files_in_dir}")


            # ZIPファイルの作成
            zip_path = f"{album_dir}.zip"
            with zipfile.ZipFile(zip_path, 'w') as zipf:
                for file in os.listdir(album_dir):
                    if file.endswith('.mp3'):
                        file_path = os.path.join(album_dir, file)
                        # ファイル名を曲名に変更
                        try:
                            audio = ID3(file_path)
                            title = audio.get('TIT2', ['Unknown Title'])[0]
                            # 安全なファイル名に変換
                            safe_title = "".join(c for c in str(title) if c.isalnum() or c in (' ', '-', '_')).rstrip()
                            archive_path = os.path.join(safe_album_title, f"{safe_title}.mp3")
                        except:
                            # タグ取得に失敗した場合は元のファイル名を使用
                            archive_path = os.path.join(safe_album_title, file)
                        
                        logger.info(f"Adding to ZIP: {file_path} as {archive_path}")
                        zipf.write(file_path, archive_path)
                        

            # ZIP後の確認
            if os.path.exists(zip_path):
                zip_size = os.path.getsize(zip_path)
                logger.info(f"Created ZIP file: {zip_path}, size: {zip_size} bytes")
                
                # ファイルを読み込んでからクリーンアップ
                with open(zip_path, 'rb') as f:
                    content = f.read()

                # クリーンアップ
                shutil.rmtree(album_dir, ignore_errors=True)
                os.remove(zip_path)

                # バイナリレスポンスを返す
                return Response(
                    content=content,
                    media_type='application/zip',
                    headers={
                        'Content-Disposition': f'attachment; filename="{safe_album_title}.zip"'
                    }
                )

        else:
            logger.info("No playlist found in URL")
            return {"message": "No playlist found in URL"}

    except Exception as e:
        logger.error(f"Error processing request: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    
    
async def cleanup_album_files(zip_path: str, album_dir: str):
    """アルバムの一時ファイルをクリーンアップする"""
    try:
        await cleanup_temp_file(zip_path)  # awaitを追加
        import shutil
        shutil.rmtree(album_dir)
    except Exception as e:
        logger.error(f"Error during cleanup: {e}")
