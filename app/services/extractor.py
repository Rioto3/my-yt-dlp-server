import yt_dlp
import os
import asyncio
import logging
from typing import Dict
from fastapi import HTTPException
from mutagen.easyid3 import EasyID3
from mutagen.id3 import ID3, APIC, error
import requests
from PIL import Image
import io

logger = logging.getLogger(__name__)

class AudioExtractor:

    def __init__(self):
        self.temp_dir = "temp"
        os.makedirs(self.temp_dir, exist_ok=True)
        
        # cookiesファイルパスの設定
        current_dir = os.path.dirname(os.path.abspath(__file__))
        self.cookies_path = os.path.join(current_dir, 'cookies.firefox-private.txt')
        
        # yt-dlpオプションの改善
        self.ydl_opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '320',
            }],
            'writethumbnail': True,
            'outtmpl': f'{self.temp_dir}/%(id)s.%(ext)s',
            'quiet': False,
            'no_warnings': False,
            'cookiefile': self.cookies_path,
            'extract_flat': True,
            'noplaylist': False,
            # 以下の設定を追加
            'sleep_interval': 5,  # リクエスト間の遅延を追加
            'max_sleep_interval': 10,
            'geo_bypass': True,
            'geo_bypass_country': 'US',
            # より一般的なユーザーエージェントに変更
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            }
        }


    # _get_video_infoメソッド内のvideo_optsの設定も修正


    async def _get_video_info(self, url: str) -> Dict:
        """動画の情報を取得"""
        try:
            # まず正しい動画IDを取得
            video_id = self._extract_video_id(url)
            logger.info(f"Extracted video ID from URL: {video_id}")

            # プレイリスト情報用の設定
            playlist_opts = {
                **self.ydl_opts,
                'extract_flat': True,
                'noplaylist': False,
            }

            # 単一動画情報用の設定
            video_opts = {
                **self.ydl_opts,
                'extract_flat': False,
                'noplaylist': True,
                'verbose': True  # より詳細なログを有効化
            }
            # cookiesfileの指定は既に初期化時に含まれているので不要
            

            with yt_dlp.YoutubeDL(playlist_opts) as ydl:
                try:
                    # プレイリスト情報の取得を試みる
                    playlist_info = await asyncio.to_thread(ydl.extract_info, url, download=False)
                    
                    # プレイリスト情報の保存
                    playlist_data = None
                    if playlist_info.get('_type') == 'playlist':
                        playlist_data = {
                            'playlist_title': playlist_info.get('title'),
                            'playlist_id': playlist_info.get('id'),
                        }
                        logger.info(f"Found playlist info: {playlist_data}")
                        logger.info("===================================")
                        logger.info(playlist_info)
                        
                        logger.info("===================================")
                        
                        
                    
                    
                    # 単一動画の情報を取得
                    with yt_dlp.YoutubeDL(video_opts) as video_ydl:
                        video_url = f"https://www.youtube.com/watch?v={video_id}"
                        video_info = await asyncio.to_thread(video_ydl.extract_info, video_url, download=False)

                        if not video_info or 'id' not in video_info:
                            raise HTTPException(status_code=400, detail="Video not found")

                        # プレイリスト情報があれば追加
                        if playlist_data:
                            video_info.update(playlist_data)

                        logger.info(f"Successfully retrieved video info - Title: {video_info.get('title')}, ID: {video_info.get('id')}")
                        return video_info

                except yt_dlp.utils.ExtractorError as e:
                    logger.error(f"Extractor error: {str(e)}")
                    raise HTTPException(status_code=400, detail=f"Could not extract video info: {str(e)}")
                except yt_dlp.utils.DownloadError as e:
                    logger.error(f"Download error: {str(e)}")
                    raise HTTPException(status_code=400, detail=f"Video not available: {str(e)}")

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}")
            raise HTTPException(status_code=400, detail="Could not process video URL")

    def center_crop_square(self, img: Image.Image) -> Image.Image:
        """画像を中央から正方形にクロップ"""
        width, height = img.size
        if width == height:
            return img
        
        new_size = min(width, height)
        # 中央を基準にクロップする位置を計算
        left = (width - new_size) // 2
        top = (height - new_size) // 2
        right = left + new_size
        bottom = top + new_size
        
        # クロップを実行
        logger.info(f"Cropping image from {width}x{height} to {new_size}x{new_size}")
        return img.crop((left, top, right, bottom))
        
        
    async def cleanup_old_files(self, keep_latest: int = 5):
        """最新のN個以外の一時ファイルを削除"""
        try:
            files = []
            for f in os.listdir(self.temp_dir):
                path = os.path.join(self.temp_dir, f)
                if os.path.isfile(path):
                    files.append((path, os.path.getmtime(path)))
            
            # 更新時刻で並べ替え
            files.sort(key=lambda x: x[1], reverse=True)
            
            # 古いファイルを削除
            for file_path, _ in files[keep_latest:]:
                try:
                    os.remove(file_path)
                    logger.info(f"Cleaned up old file: {file_path}")
                except Exception as e:
                    logger.error(f"Error deleting file {file_path}: {e}")
                    
            return len(files[keep_latest:])  # 削除したファイル数を返す
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
            return 0



    async def extract(self, url: str, output_dir: str = None) -> Dict:
        """音声を抽出してタグを設定"""
        retry_count = 3  # リトライ回数を設定
        retry_delay = 2  # リトライ間の待機時間（秒）

        for attempt in range(retry_count):
            try:
                info = await self._get_video_info(url)
                if not info:
                    raise HTTPException(status_code=400, detail="Could not get video information")

                # 保存先ディレクトリを設定
                original_temp_dir = self.temp_dir
                if output_dir:
                    self.temp_dir = output_dir
                    logger.info(f"Using custom output directory: {output_dir}")

                try:
                    output_file = await self._download_and_convert(url, info['id'])
                    
                    # ファイルの存在確認
                    if not os.path.exists(output_file):
                        raise Exception(f"File was not saved properly: {output_file}")
                    
                    # ファイルサイズの確認
                    file_size = os.path.getsize(output_file)
                    if file_size == 0:
                        raise Exception(f"File is empty: {output_file}")

                    await self._set_media_tags(output_file, info)
                    safe_title = "".join(c for c in info['title'] if c.isalnum() or c in (' ', '-', '_')).rstrip()
                    
                    # MP3ファイルとして正しく保存されているか確認
                    try:
                        audio = ID3(output_file)
                        logger.info(f"Successfully verified MP3 file: {safe_title}")
                    except Exception as e:
                        raise Exception(f"Invalid MP3 file: {str(e)}")

                    result = {
                        "video_id": info['id'],
                        "title": info['title'],
                        "duration": info.get('duration'),
                        "file_path": output_file,
                        "filename": f"{safe_title}.mp3"
                    }

                    # プレイリスト処理時はクリーンアップしない
                    if not output_dir:
                        cleaned = await self.cleanup_old_files(keep_latest=5)
                        if cleaned > 0:
                            logger.info(f"Cleaned up {cleaned} old files")

                    return result

                finally:
                    # 元のtemp_dirを復元
                    if output_dir:
                        self.temp_dir = original_temp_dir

            except Exception as e:
                logger.error(f"Attempt {attempt + 1}/{retry_count} failed: {str(e)}")
                if attempt < retry_count - 1:  # 最後の試行でなければ
                    logger.info(f"Retrying in {retry_delay} seconds...")
                    await asyncio.sleep(retry_delay)  # 次の試行前に待機
                else:  # 最後の試行で失敗した場合
                    if isinstance(e, HTTPException):
                        raise
                    raise HTTPException(status_code=400, detail=str(e))



    async def _set_media_tags(self, file_path: str, info: Dict) -> None:
        """メディアタグを設定"""
        try:
            # メタデータの設定
            try:
                audio = EasyID3(file_path)
            except error:
                audio = ID3()
                audio.save(file_path)
                audio = EasyID3(file_path)

            # 基本的なメタデータを設定
            title = info.get('title', '')
            artist = info.get('uploader', '')
            album = info.get('playlist_title', '') or info.get('album', 'YouTube Music')

            audio['title'] = title
            audio['artist'] = artist
            audio['album'] = album
            if info.get('upload_date'):
                audio['date'] = info['upload_date'][:4]
            audio.save()

            # 画像の設定
            thumbnails = [
                info.get('thumbnail'),
                next((t['url'] for t in info.get('thumbnails', []) if t.get('url')), None),
                f"https://i.ytimg.com/vi/{info['id']}/maxresdefault.jpg",
                f"https://i.ytimg.com/vi/{info['id']}/hqdefault.jpg"
            ]
            
            thumbnail_url = next((url for url in thumbnails if url), None)
            logger.info(f"Selected thumbnail URL: {thumbnail_url}")

            if thumbnail_url:
                response = requests.get(thumbnail_url)
                if response.status_code == 200:
                    # 画像をPILで開く
                    img = Image.open(io.BytesIO(response.content))
                    if img.mode != 'RGB':
                        img = img.convert('RGB')
                    
                    # 画像を正方形にクロップ
                    img = self.center_crop_square(img)
                    
                    # JPEG形式で保存
                    output = io.BytesIO()
                    img.save(output, format='JPEG', quality=95)
                    image_data = output.getvalue()
                    
                    # ID3タグに画像を追加
                    audio = ID3(file_path)
                    audio.delall('APIC')  # 既存の画像を削除
                    
                    audio.add(APIC(
                        encoding=3,
                        mime='image/jpeg',
                        type=3,
                        desc='Cover',
                        data=image_data
                    ))
                    audio.save(v2_version=3)
                    
                    # 検証
                    verify_audio = ID3(file_path)
                    apic_frames = verify_audio.getall('APIC')
                    logger.info(f"Embedded image size: {len(image_data)} bytes")
                    logger.info(f"Number of APIC frames: {len(apic_frames)}")
                    logger.info(f"Set metadata - Title: {title}, Artist: {artist}, Album: {album}")

        except Exception as e:
            logger.error(f"Error setting media tags: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
                        
    # _download_and_convertメソッドを修正
    async def _download_and_convert(self, url: str, video_id: str) -> str:
        try:
            # cookiesファイルの設定
            current_dir = os.path.dirname(os.path.abspath(__file__))
            cookies_path = os.path.join(current_dir, 'cookies.firefox-private.txt')
            
            # 出力ディレクトリの設定と確認
            os.makedirs(self.temp_dir, exist_ok=True)
            
            # フォーマットを明示的に指定してダウンロード
            current_opts = {
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '320',
                }],
                'writethumbnail': True,
                'outtmpl': os.path.join(self.temp_dir, '%(id)s.%(ext)s'),
                'cookiefile': cookies_path,
                'noplaylist': True,  # プレイリストを無視
                'sleep_interval': 5,
                'geo_bypass': True,
                'geo_bypass_country': 'US',
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                    'Accept-Language': 'en-US,en;q=0.9',
                },
                'verbose': True,
                # 直接ダウンロードURLのみ取得するオプション
                'skip_download': False,
                'progress': True
            }
            
            logger.info(f"直接ダウンロード試行: {url} → {self.temp_dir}/{video_id}")
            
            # まず動画自体をダウンロード（mp3変換せず）
            download_opts = current_opts.copy()
            download_opts['postprocessors'] = []  # 後処理を無効化
            
            with yt_dlp.YoutubeDL(download_opts) as ydl:
                # まず動画をダウンロード
                await asyncio.to_thread(ydl.download, [url])
                
                # ダウンロードした動画ファイルを探す
                video_files = [f for f in os.listdir(self.temp_dir) 
                            if f.startswith(video_id) and not f.endswith('.webp')]
                
                if not video_files:
                    logger.error(f"動画ファイルが見つかりません: {self.temp_dir}内のファイル: {os.listdir(self.temp_dir)}")
                    raise Exception("ダウンロードに失敗しました")
                
                # 最初の動画ファイルを取得
                video_file = os.path.join(self.temp_dir, video_files[0])
                logger.info(f"ダウンロードした動画ファイル: {video_file}")
                
                # FFmpegで直接変換
                output_file = os.path.join(self.temp_dir, f"{video_id}.mp3")
                ffmpeg_cmd = [
                    'ffmpeg', '-i', video_file, 
                    '-vn', '-ar', '44100', '-ac', '2', '-b:a', '320k',
                    output_file
                ]
                
                logger.info(f"FFmpeg変換コマンド: {' '.join(ffmpeg_cmd)}")
                
                try:
                    process = await asyncio.create_subprocess_exec(
                        *ffmpeg_cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE
                    )
                    stdout, stderr = await process.communicate()
                    
                    if process.returncode != 0:
                        logger.error(f"FFmpeg変換エラー: {stderr.decode()}")
                        raise Exception(f"FFmpeg変換失敗: {stderr.decode()}")
                    
                    logger.info(f"FFmpeg変換成功: {output_file}")
                    
                    # 元の動画ファイルを削除
                    os.remove(video_file)
                except Exception as e:
                    logger.error(f"FFmpeg実行エラー: {str(e)}")
                    raise
                
                # 変換後のファイルを確認
                if not os.path.exists(output_file):
                    logger.error(f"MP3ファイルが見つかりません: {output_file}")
                    raise Exception("MP3変換に失敗しました")
                
                file_size = os.path.getsize(output_file)
                if file_size == 0:
                    raise Exception(f"空のMP3ファイル: {output_file}")
                    
                logger.info(f"MP3変換成功: {output_file} ({file_size} bytes)")
                return output_file

        except Exception as e:
            logger.error(f"変換処理エラー: {str(e)}")
            logger.error(f"エラータイプ: {type(e)}")
            import traceback
            logger.error(f"トレース: {traceback.format_exc()}")
            raise HTTPException(status_code=400, detail=f"ダウンロードまたは変換に失敗: {str(e)}")  
            
            
            
            
                
    def _extract_video_id(self, url: str) -> str:
        """URLから動画IDを抽出"""
        import urllib.parse

        # URLをパース
        parsed_url = urllib.parse.urlparse(url)
        query_params = urllib.parse.parse_qs(parsed_url.query)
        
        # 'v' パラメータから動画IDを取得
        video_id = query_params.get('v', [None])[0]
        
        if not video_id:
            # youtu.be形式の場合
            if 'youtu.be' in url:
                video_id = parsed_url.path.strip('/')
        
        if not video_id or len(video_id) != 11:
            logger.error(f"Invalid video ID extracted from URL: {url}")
            raise HTTPException(status_code=400, detail="Could not extract valid video ID")
        
        logger.info(f"Extracted video ID: {video_id}")
        return video_id


    def _is_valid_youtube_url(self, url: str) -> bool:
        """YouTubeのURLが有効かチェック"""
        import re
        import urllib.parse
        
        try:
            parsed_url = urllib.parse.urlparse(url)
            query_params = urllib.parse.parse_qs(parsed_url.query)
            
            # 通常の動画ID
            video_id = query_params.get('v', [None])[0]
            if not video_id:
                # youtu.be形式の確認
                video_id = parsed_url.path.strip('/')
            
            # Radio/Mixリストの場合は特別な処理
            if 'start_radio' in query_params:
                logger.info("Detected Radio/Mix playlist")
                # 最初の動画のみを処理
                return bool(video_id and len(video_id) == 11)
                
            return bool(video_id and len(video_id) == 11)
            
        except Exception as e:
            logger.error(f"Error parsing URL: {str(e)}")
            return False
        
        
        
        
    async def get_playlist_info(self, url: str) -> Dict:
        """プレイリストの情報を取得"""
        playlist_opts = {
            **self.ydl_opts,
            'extract_flat': True,  # プレイリスト情報のみを取得
            'noplaylist': False    # プレイリストを許可
        }

        try:
            with yt_dlp.YoutubeDL(playlist_opts) as ydl:
                info = await asyncio.to_thread(ydl.extract_info, url, download=False)
                logger.info(f"Retrieved playlist info with {len(info.get('entries', []))} videos")
                return info
        except Exception as e:
            logger.error(f"Error getting playlist info: {str(e)}")
            raise HTTPException(status_code=400, detail=f"Could not get playlist info: {str(e)}")