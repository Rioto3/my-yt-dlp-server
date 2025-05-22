import os
import tempfile
import subprocess
import json
import re
import asyncio
from pathlib import Path
from typing import Dict, Optional
import logging

logger = logging.getLogger(__name__)

class TranscriptService:
    def __init__(self):
        self.temp_dir = tempfile.mkdtemp(prefix="yt_transcript_")
        
    async def extract_transcript(self, url: str) -> Dict[str, str]:
        """
        YouTubeの動画からトランスクリプトを抽出し、フォーマットして返却
        """
        try:
            # 動画情報を取得
            video_info = await self._get_video_info(url)
            
            # 字幕ファイルをダウンロード
            subtitle_files = await self._download_subtitles(url)
            
            # 字幕ファイルを解析
            subtitle_data = self._parse_subtitle_file(subtitle_files)
            
            # フォーマットされたトランスクリプトを生成
            formatted_transcript = self._format_transcript(
                video_info, 
                subtitle_data, 
                url
            )
            
            return {
                'title': video_info['title'],
                'duration': self._format_duration(video_info.get('duration', 0)),
                'language': subtitle_data['language'],
                'subtitle_type': subtitle_data['type'],
                'formatted_transcript': formatted_transcript
            }
            
        except Exception as e:
            logger.error(f"トランスクリプト抽出エラー: {str(e)}")
            raise
    
    async def _get_video_info(self, url: str) -> Dict:
        """動画の基本情報を取得"""
        cmd = [
            'yt-dlp',
            '--dump-json',
            '--no-download',
            url
        ]
        
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.temp_dir
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode != 0:
                raise Exception(f"動画情報取得失敗: {stderr.decode()}")
            
            return json.loads(stdout.decode())
            
        except Exception as e:
            logger.error(f"動画情報取得エラー: {str(e)}")
            raise
    
    async def _download_subtitles(self, url: str) -> Dict[str, str]:
        """字幕ファイルをダウンロード"""
        cmd = [
            'yt-dlp',
            '--write-sub',           # 手動字幕
            '--write-auto-sub',      # 自動生成字幕
            '--sub-lang', 'ja,en',   # 日本語、英語の順で試行
            '--sub-format', 'vtt',   # VTT形式
            '--skip-download',       # 動画本体はダウンロードしない
            '--output', '%(title)s.%(ext)s',
            url
        ]
        
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.temp_dir
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode != 0:
                logger.warning(f"字幕ダウンロード警告: {stderr.decode()}")
            
            # ダウンロードされた字幕ファイルを検索
            return self._find_subtitle_files()
            
        except Exception as e:
            logger.error(f"字幕ダウンロードエラー: {str(e)}")
            raise
    
    def _find_subtitle_files(self) -> Dict[str, str]:
        """ダウンロードされた字幕ファイルを検索"""
        subtitle_files = {}
        
        for file_path in Path(self.temp_dir).glob("*.vtt"):
            file_name = file_path.name
            
            # 手動字幕を優先
            if '.ja.vtt' in file_name:
                subtitle_files['manual_ja'] = str(file_path)
            elif '.en.vtt' in file_name:
                subtitle_files['manual_en'] = str(file_path)
            # 自動生成字幕
            elif '.ja.auto.vtt' in file_name:
                subtitle_files['auto_ja'] = str(file_path)
            elif '.en.auto.vtt' in file_name:
                subtitle_files['auto_en'] = str(file_path)
        
        if not subtitle_files:
            raise FileNotFoundError("字幕ファイルが見つかりませんでした")
        
        return subtitle_files
    
    def _parse_subtitle_file(self, subtitle_files: Dict[str, str]) -> Dict[str, str]:
        """字幕ファイルを解析してテキストを抽出"""
        # 優先順位: 手動日本語 > 自動日本語 > 手動英語 > 自動英語
        priority_order = ['manual_ja', 'auto_ja', 'manual_en', 'auto_en']
        
        selected_file = None
        selected_type = None
        selected_lang = None
        
        for file_type in priority_order:
            if file_type in subtitle_files:
                selected_file = subtitle_files[file_type]
                selected_type = 'manual' if 'manual' in file_type else 'auto'
                selected_lang = '日本語' if 'ja' in file_type else '英語'
                break
        
        if not selected_file:
            raise FileNotFoundError("利用可能な字幕ファイルがありません")
        
        # VTTファイルを読み込み
        with open(selected_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # VTTからテキストを抽出
        text_content = self._extract_text_from_vtt(content)
        
        return {
            'text': text_content,
            'language': selected_lang,
            'type': selected_type
        }
    
    def _extract_text_from_vtt(self, vtt_content: str) -> str:
        """VTTファイルからテキスト部分のみを抽出"""
        lines = vtt_content.split('\n')
        text_lines = []
        
        skip_next = False
        for line in lines:
            line = line.strip()
            
            # ヘッダー行をスキップ
            if line.startswith('WEBVTT') or line.startswith('Kind:') or line.startswith('Language:'):
                continue
            
            # タイムスタンプ行をスキップ
            if re.match(r'\d{2}:\d{2}:\d{2}\.\d{3} --> \d{2}:\d{2}:\d{2}\.\d{3}', line):
                skip_next = True
                continue
            
            # 空行をスキップ
            if not line:
                skip_next = False
                continue
            
            # position情報などをスキップ
            if 'align:' in line or 'position:' in line:
                continue
            
            # テキスト行を処理
            if not skip_next and line:
                # HTMLタグを除去
                clean_text = re.sub(r'<[^>]+>', '', line)
                # 特殊なタイムスタンプタグを除去
                clean_text = re.sub(r'<\d{2}:\d{2}:\d{2}\.\d{3}>', '', clean_text)
                clean_text = re.sub(r'<c[^>]*>', '', clean_text)
                clean_text = re.sub(r'</c>', '', clean_text)
                
                if clean_text.strip():
                    text_lines.append(clean_text.strip())
        
        # テキストを結合して整形
        full_text = ' '.join(text_lines)
        
        # 重複を除去し、読みやすく整形
        return self._clean_and_format_text(full_text)
    
    def _clean_and_format_text(self, text: str) -> str:
        """テキストをクリーニングして読みやすく整形"""
        # 同じフレーズの重複を除去
        sentences = text.split('。')
        unique_sentences = []
        
        for sentence in sentences:
            sentence = sentence.strip()
            if sentence and sentence not in unique_sentences:
                unique_sentences.append(sentence)
        
        # 文章を再構成
        cleaned_text = '。'.join(unique_sentences)
        if not cleaned_text.endswith('。') and cleaned_text:
            cleaned_text += '。'
        
        # 長い文章を適切な箇所で改行
        formatted_text = self._add_paragraph_breaks(cleaned_text)
        
        return formatted_text
    
    def _add_paragraph_breaks(self, text: str) -> str:
        """長いテキストに適切な段落区切りを追加"""
        sentences = text.split('。')
        paragraphs = []
        current_paragraph = []
        
        for sentence in sentences:
            sentence = sentence.strip()
            if sentence:
                current_paragraph.append(sentence)
                
                # 3-4文ごと、または特定のキーワードで段落を区切る
                if (len(current_paragraph) >= 3 or 
                    any(keyword in sentence for keyword in ['です', 'ます', 'でしょう', 'ですね'])):
                    paragraphs.append('。'.join(current_paragraph) + '。')
                    current_paragraph = []
        
        # 残りの文章があれば追加
        if current_paragraph:
            paragraphs.append('。'.join(current_paragraph) + '。')
        
        return '\n'.join(paragraphs)
    
    def _format_transcript(self, video_info: Dict, subtitle_data: Dict, url: str) -> str:
        """指定されたフォーマットでトランスクリプトを整形"""
        template = """=== YouTube動画yt-dlpトランスクリプト ===
タイトル: {title}
URL: {url}
言語: {language} ({subtitle_type})
時間: {duration}
--- 内容 ---
{content}"""
        
        return template.format(
            title=video_info['title'],
            url=url,
            language=subtitle_data['language'],
            subtitle_type='自動生成' if subtitle_data['type'] == 'auto' else '手動',
            duration=self._format_duration(video_info.get('duration', 0)),
            content=subtitle_data['text']
        )
    
    def _format_duration(self, seconds: int) -> str:
        """秒数を読みやすい時間形式に変換"""
        if seconds < 60:
            return f"{seconds}秒"
        elif seconds < 3600:
            minutes = seconds // 60
            remaining_seconds = seconds % 60
            return f"{minutes}分{remaining_seconds}秒"
        else:
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            remaining_seconds = seconds % 60
            return f"{hours}時間{minutes}分{remaining_seconds}秒"