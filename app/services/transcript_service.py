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
            logger.info(f"見つかった字幕ファイル: {file_name}")
            
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
        
        logger.info(f"利用可能な字幕ファイル: {subtitle_files}")
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
        
        logger.info(f"選択された字幕ファイル: {selected_file} ({selected_type} {selected_lang})")
        
        # VTTファイルを読み込み
        with open(selected_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        logger.info(f"VTTファイルサイズ: {len(content)} 文字")
        
        # VTTからテキストを抽出
        text_content = self._extract_text_from_vtt(content)
        
        return {
            'text': text_content,
            'language': selected_lang,
            'type': selected_type
        }
    
    def _extract_text_from_vtt(self, vtt_content: str) -> str:
        """VTTファイルからテキスト部分のみを抽出（改良版）"""
        lines = vtt_content.split('\n')
        text_segments = []
        
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            
            # ヘッダー行をスキップ
            if line.startswith('WEBVTT') or line.startswith('Kind:') or line.startswith('Language:'):
                i += 1
                continue
            
            # タイムスタンプ行を検出
            if re.match(r'\d{2}:\d{2}:\d{2}\.\d{3} --> \d{2}:\d{2}:\d{2}\.\d{3}', line):
                i += 1
                # タイムスタンプの後のテキスト行を取得
                text_lines = []
                while i < len(lines):
                    text_line = lines[i].strip()
                    if not text_line:  # 空行で区切り終了
                        break
                    if re.match(r'\d{2}:\d{2}:\d{2}\.\d{3} --> \d{2}:\d{2}:\d{2}\.\d{3}', text_line):
                        # 次のタイムスタンプが見つかったら戻る
                        i -= 1
                        break
                    
                    # テキストをクリーニング
                    clean_text = self._clean_vtt_text(text_line)
                    if clean_text:
                        text_lines.append(clean_text)
                    i += 1
                
                # セグメントのテキストを結合
                if text_lines:
                    segment_text = ' '.join(text_lines)
                    if segment_text:
                        text_segments.append(segment_text)
            
            i += 1
        
        logger.info(f"抽出されたセグメント数: {len(text_segments)}")
        
        # 全セグメントを結合
        full_text = ' '.join(text_segments)
        
        # 重複を除去し、読みやすく整形
        return self._clean_and_format_text(full_text)
    
    def _clean_vtt_text(self, text: str) -> str:
        """VTTテキスト行のクリーニング"""
        # HTMLタグを除去
        text = re.sub(r'<[^>]+>', '', text)
        
        # VTTの特殊なタイムスタンプタグを除去
        text = re.sub(r'<\d{2}:\d{2}:\d{2}\.\d{3}>', '', text)
        
        # VTTのスタイルタグを除去
        text = re.sub(r'<c[^>]*>', '', text)
        text = re.sub(r'</c>', '', text)
        
        # 位置情報を除去
        if 'align:' in text or 'position:' in text:
            return ''
        
        # 音楽記号を除去
        text = re.sub(r'♪.*?♪', '', text)
        text = re.sub(r'\[音楽\]', '', text)
        text = re.sub(r'\[Music\]', '', text)
        
        return text.strip()
    
    def _clean_and_format_text(self, text: str) -> str:
        """テキストをクリーニングして読みやすく整形（改良版）"""
        if not text:
            return ""
        
        # 基本的なクリーニング
        text = re.sub(r'\s+', ' ', text)  # 複数の空白を1つに
        text = text.strip()
        
        # 重複フレーズの除去（より寛容に）
        words = text.split()
        unique_words = []
        
        # 連続する同じ単語を除去
        prev_word = None
        for word in words:
            if word != prev_word:
                unique_words.append(word)
            prev_word = word
        
        text = ' '.join(unique_words)
        
        # 日本語の場合の特別処理
        if self._is_japanese_text(text):
            text = self._format_japanese_text(text)
        else:
            text = self._format_english_text(text)
        
        return text
    
    def _is_japanese_text(self, text: str) -> bool:
        """テキストが日本語かどうかを判定"""
        # ひらがな、カタカナ、漢字が含まれているかチェック
        japanese_chars = re.findall(r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FAF]', text)
        return len(japanese_chars) > len(text) * 0.3  # 30%以上が日本語文字
    
    def _format_japanese_text(self, text: str) -> str:
        """日本語テキストの整形"""
        # 句読点での区切りを整理
        sentences = re.split(r'[。！？]', text)
        formatted_sentences = []
        
        current_paragraph = []
        for sentence in sentences:
            sentence = sentence.strip()
            if sentence:
                current_paragraph.append(sentence)
                
                # 3-4文ごとまたは特定の語尾で段落を区切る
                if (len(current_paragraph) >= 3 or 
                    any(ending in sentence for ending in ['です', 'ます', 'でした', 'ました', 'だった', 'である'])):
                    paragraph_text = '。'.join(current_paragraph) + '。'
                    formatted_sentences.append(paragraph_text)
                    current_paragraph = []
        
        # 残りの文があれば追加
        if current_paragraph:
            paragraph_text = '。'.join(current_paragraph) + '。'
            formatted_sentences.append(paragraph_text)
        
        return '\n'.join(formatted_sentences)
    
    def _format_english_text(self, text: str) -> str:
        """英語テキストの整形"""
        # 文の区切りを整理
        sentences = re.split(r'[.!?]', text)
        formatted_sentences = []
        
        current_paragraph = []
        for sentence in sentences:
            sentence = sentence.strip()
            if sentence:
                # 最初の文字を大文字に
                sentence = sentence[0].upper() + sentence[1:] if len(sentence) > 1 else sentence.upper()
                current_paragraph.append(sentence)
                
                # 3-4文ごとに段落を区切る
                if len(current_paragraph) >= 4:
                    paragraph_text = '. '.join(current_paragraph) + '.'
                    formatted_sentences.append(paragraph_text)
                    current_paragraph = []
        
        # 残りの文があれば追加
        if current_paragraph:
            paragraph_text = '. '.join(current_paragraph) + '.'
            formatted_sentences.append(paragraph_text)
        
        return '\n\n'.join(formatted_sentences)
    
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