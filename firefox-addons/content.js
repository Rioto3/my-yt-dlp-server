// content.js
/*
 * YouTube MP3ダウンローダー + トランスクリプト Content Script
 * 
 * 設計思想：
 * - YouTube動画/プレイリストページおよび検索結果ページにMP3ダウンロードボタンとトランスクリプトボタンを追加するContent Script
 * - シンプルで保守性の高いクラスベースのアーキテクチャを採用
 * - 各クラスは単一責任の原則に従い、明確な役割を持つ
 * 
 * 主要コンポーネント：
 * - Config: 設定値の集約による保守性の向上
 * - FileUtils: ファイル操作に関する共通処理
 * - AudioExtractorService: APIとの通信を担当
 * - TranscriptService: トランスクリプト取得とクリップボード操作を担当
 * - DownloadManager: ダウンロード処理の統合管理
 * - MP3ButtonManager: UIコンポーネントとユーザーインタラクションの管理
 * - SearchResultsButtonManager: 検索結果ページのボタン管理
 * 
 * 拡張性：
 * - 新機能の追加が容易な構造
 * - APIエンドポイントの追加や変更が設定で完結
 * - UI要素の追加や変更が分離された形で可能
 */

// 設定の名前空間
const Config = {
  API: {
    BASE_URL: 'http://localhost:7783/api/v1',
    ENDPOINTS: {
      EXTRACT_AUDIO: '/extract-audio',
      EXTRACT_ALBUM: '/extract-album',
      EXTRACT_TRANSCRIPT: '/extract-transcript'  // 新規追加
    }
  },
  UI: {
    BUTTON_STYLES: `
      .mp3-save-btn, .transcript-btn {
        display: block;
        margin: 10px auto;
        padding: 10px 20px;
        border: none;
        border-radius: 4px;
        cursor: pointer;
        transition: background-color 0.3s ease;
        color: white;
      }
      .mp3-save-btn:hover, .transcript-btn:hover {
        filter: brightness(0.95);
      }
      .mp3-save-btn.loading, .transcript-btn.loading {
        background-color: #ccc;
        cursor: wait;
      }
      .mp3-save-btn-search, .transcript-btn-search {
        display: inline-block;
        margin: 5px 0;
        padding: 8px 16px;
        font-size: 0.9em;
      }
      .transcript-btn {
        background-color: #1976d2;
      }
      .transcript-btn:hover {
        background-color: #1565c0;
      }
      .transcript-btn.success {
        background-color: #4caf50;
      }
      .transcript-btn.error {
        background-color: #f44336;
      }
    `,
    CONTAINER_SELECTORS: [
      'div#actions.ytd-video-primary-info-renderer',
      'div#actions-inner',
      'ytd-video-primary-info-renderer #actions',
      '#top-row.ytd-video-primary-info-renderer'
    ],
    SEARCH_RESULT_SELECTORS: {
      VIDEO_ITEMS: 'ytd-video-renderer',
      BUTTON_CONTAINER: '#meta',
      METADATA_CONTAINER: '#metadata-line'
    }
  }
};

// ユーティリティクラス
class FileUtils {
  static getFilenameFromResponse(response) {
    const disposition = response.headers.get('content-disposition');
    if (!disposition) return 'downloaded.mp3';

    const utf8Match = /filename\*=UTF-8''(.+)/.exec(disposition);
    if (utf8Match?.[1]) {
      return decodeURIComponent(utf8Match[1]);
    }

    const standardMatch = /filename="(.+)"/.exec(disposition);
    return standardMatch?.[1] || 'downloaded.mp3';
  }

  static async downloadBlob(blob, filename) {
    const link = document.createElement('a');
    link.href = window.URL.createObjectURL(blob);
    link.download = filename;
    link.click();
    window.URL.revokeObjectURL(link.href);
  }

  static getVideoIdFromElement(element) {
    const videoLink = element.querySelector('a#video-title');
    if (!videoLink) return null;
    
    const href = videoLink.href;
    const match = href.match(/[?&]v=([^&]+)/);
    return match ? match[1] : null;
  }

  static showNotification(message, type = 'info') {
    const notification = document.createElement('div');
    notification.style.cssText = `
      position: fixed;
      top: 20px;
      right: 20px;
      padding: 12px 20px;
      border-radius: 4px;
      color: white;
      font-weight: 500;
      z-index: 10000;
      transition: opacity 0.3s;
      ${type === 'success' ? 'background: #4caf50;' : ''}
      ${type === 'error' ? 'background: #f44336;' : ''}
      ${type === 'info' ? 'background: #2196f3;' : ''}
    `;
    notification.textContent = message;
    
    document.body.appendChild(notification);
    
    // 3秒後に削除
    setTimeout(() => {
      notification.style.opacity = '0';
      setTimeout(() => {
        if (notification.parentNode) {
          notification.parentNode.removeChild(notification);
        }
      }, 300);
    }, 3000);
  }
}

// APIサービスクラス
class AudioExtractorService {
  async extractAudio(url, endpoint) {
    const response = await fetch(`${Config.API.BASE_URL}${endpoint}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': '*/*'
      },
      body: JSON.stringify({ url })
    });

    if (!response.ok) {
      const errorData = await response.json();
      throw new Error(errorData.detail || '音声抽出に失敗しました');
    }

    return response;
  }
}

// トランスクリプトサービスクラス
class TranscriptService {
  async extractTranscript(url) {
    const response = await fetch(`${Config.API.BASE_URL}${Config.API.ENDPOINTS.EXTRACT_TRANSCRIPT}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json'
      },
      body: JSON.stringify({ url })
    });

    if (!response.ok) {
      const errorData = await response.json();
      throw new Error(errorData.detail || 'トランスクリプト取得に失敗しました');
    }

    const result = await response.json();
    return result.transcript;
  }

  async copyToClipboard(text) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (error) {
      console.error('クリップボードへのコピーに失敗:', error);
      return false;
    }
  }

  async handleTranscriptRequest(button, videoId = null) {
    const originalText = button.textContent;
    
    try {
      // ボタンを処理中状態に変更
      button.classList.add('loading');
      button.textContent = '⏳ 処理中...';
      
      // URLを構築
      const url = videoId 
        ? `https://www.youtube.com/watch?v=${videoId}`
        : window.location.href;
      
      // トランスクリプト取得
      const transcript = await this.extractTranscript(url);
      
      // クリップボードにコピー
      const copySuccess = await this.copyToClipboard(transcript);
      
      if (copySuccess) {
        // 成功状態
        button.classList.remove('loading');
        button.classList.add('success');
        button.textContent = '✅ コピー完了!';
        
        FileUtils.showNotification('トランスクリプトをクリップボードにコピーしました!', 'success');
      } else {
        throw new Error('クリップボードへのコピーに失敗しました');
      }
      
    } catch (error) {
      console.error('トランスクリプト取得エラー:', error);
      
      // エラー状態
      button.classList.remove('loading');
      button.classList.add('error');
      button.textContent = '❌ エラー';
      
      FileUtils.showNotification(`エラー: ${error.message}`, 'error');
    } finally {
      // 3秒後に元の状態に戻す
      setTimeout(() => {
        button.classList.remove('loading', 'success', 'error');
        button.textContent = originalText;
      }, 3000);
    }
  }
}

// ダウンロード管理クラス
class DownloadManager {
  constructor() {
    this.service = new AudioExtractorService();
  }

  async handleDownload(button, endpoint, successMessage, videoId = null) {
    const originalText = button.textContent;
    try {
      button.classList.add('loading');
      button.textContent = 'ダウンロード中...';

      const url = videoId 
        ? `https://www.youtube.com/watch?v=${videoId}`
        : window.location.href;

      const response = await this.service.extractAudio(
        url,
        endpoint
      );

      const blob = await response.blob();
      const filename = FileUtils.getFilenameFromResponse(response);
      await FileUtils.downloadBlob(blob, filename);

      alert(successMessage);
    } catch (error) {
      console.error('音声抽出エラー:', error);
      alert(`エラーが発生しました: ${error.message}`);
    } finally {
      button.classList.remove('loading');
      button.textContent = originalText;
    }
  }
}

// 検索結果ページのボタン管理クラス
class SearchResultsButtonManager {
  constructor() {
    this.downloadManager = new DownloadManager();
    this.transcriptService = new TranscriptService();
  }

  createSearchResultButton(videoId, type = 'mp3') {
    const button = document.createElement('button');
    
    if (type === 'mp3') {
      button.textContent = 'MP3を保存';
      button.classList.add('mp3-save-btn', 'mp3-save-btn-search');
      button.style.backgroundColor = '#4CAF50';
      
      button.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        this.downloadManager.handleDownload(
          button,
          Config.API.ENDPOINTS.EXTRACT_AUDIO,
          'MP3ファイルが保存されました',
          videoId
        );
      });
    } else if (type === 'transcript') {
      button.textContent = '📄 トランスクリプト';
      button.classList.add('transcript-btn', 'transcript-btn-search');
      button.style.backgroundColor = '#1976d2';
      
      button.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        this.transcriptService.handleTranscriptRequest(button, videoId);
      });
    }

    return button;
  }

  addButtonToSearchResult(videoElement) {
    // 既にボタンが追加されているか確認
    if (videoElement.querySelector('.mp3-save-btn') || videoElement.querySelector('.transcript-btn')) {
      return;
    }

    const videoId = FileUtils.getVideoIdFromElement(videoElement);
    if (!videoId) {
      return;
    }

    const metadataContainer = videoElement.querySelector(
      Config.UI.SEARCH_RESULT_SELECTORS.METADATA_CONTAINER
    );
    if (!metadataContainer) {
      return;
    }

    // MP3ボタンとトランスクリプトボタンを追加
    const mp3Button = this.createSearchResultButton(videoId, 'mp3');
    const transcriptButton = this.createSearchResultButton(videoId, 'transcript');
    
    metadataContainer.appendChild(mp3Button);
    metadataContainer.appendChild(transcriptButton);
  }

  processSearchResults() {
    const videoItems = document.querySelectorAll(
      Config.UI.SEARCH_RESULT_SELECTORS.VIDEO_ITEMS
    );
    videoItems.forEach(item => this.addButtonToSearchResult(item));
  }
}

// メインの機能を管理するクラス
class MP3ButtonManager {
  constructor() {
    this.downloadManager = new DownloadManager();
    this.transcriptService = new TranscriptService();
  }

  createButton(id, text, backgroundColor, buttonClass = 'mp3-save-btn') {
    const button = document.createElement('button');
    button.id = id;
    button.textContent = text;
    button.classList.add(buttonClass);
    if (backgroundColor) {
      button.style.backgroundColor = backgroundColor;
    }
    return button;
  }

  addStyles() {
    const existingStyle = document.getElementById('mp3-button-styles');
    if (!existingStyle) {
      const style = document.createElement('style');
      style.id = 'mp3-button-styles';
      style.textContent = Config.UI.BUTTON_STYLES;
      document.head.appendChild(style);
    }
  }

  findContainer() {
    for (const selector of Config.UI.CONTAINER_SELECTORS) {
      const container = document.querySelector(selector);
      if (container) {
        return container;
      }
    }
    return null;
  }

  initialize() {
    // 既に追加されているか確認
    if (document.getElementById('mp3-save-button')) {
      return;
    }

    const container = this.findContainer();
    if (!container) {
      return;
    }

    this.addStyles();

    // 単曲ダウンロードボタン
    const singleButton = this.createButton(
      'mp3-save-button',
      'MP3を保存',
      '#4CAF50'
    );
    singleButton.addEventListener('click', () =>
      this.downloadManager.handleDownload(
        singleButton,
        Config.API.ENDPOINTS.EXTRACT_AUDIO,
        'MP3ファイルが保存されました'
      )
    );

    // プレイリストダウンロードボタン
    const playlistButton = this.createButton(
      'mp3-save-button-2',
      'プレイリストの全ての曲を保存',
      '#007BFF'
    );
    playlistButton.addEventListener('click', () =>
      this.downloadManager.handleDownload(
        playlistButton,
        Config.API.ENDPOINTS.EXTRACT_ALBUM,
        'プレイリストの全ての曲が保存されました'
      )
    );

    // トランスクリプトボタン（新規追加）
    const transcriptButton = this.createButton(
      'transcript-save-button',
      '📄 トランスクリプト',
      '#1976d2',
      'transcript-btn'
    );
    transcriptButton.addEventListener('click', () =>
      this.transcriptService.handleTranscriptRequest(transcriptButton)
    );

    // ボタンを追加
    container.appendChild(singleButton);
    container.appendChild(playlistButton);
    container.appendChild(transcriptButton);
  }
}

// メイン処理
const buttonManager = new MP3ButtonManager();
const searchResultsManager = new SearchResultsButtonManager();

function initializeButtons() {
  buttonManager.addStyles();
  
  // 現在のページURLをチェック
  const isSearchPage = window.location.pathname === '/results';
  
  if (isSearchPage) {
    searchResultsManager.processSearchResults();
  } else {
    buttonManager.initialize();
  }
}

// 初期化処理の実行
initializeButtons();

// DOMの変更を監視
const observer = new MutationObserver((mutations) => {
  const isSearchPage = window.location.pathname === '/results';
  
  if (isSearchPage) {
    searchResultsManager.processSearchResults();
  } else {
    if (!document.getElementById('mp3-save-button')) {
      buttonManager.initialize();
    }
  }
});

// オブザーバーの設定
observer.observe(document.body, {
  childList: true,
  subtree: true
});

// 遅延実行による初期化
setTimeout(() => initializeButtons(), 1000);