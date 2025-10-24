import os
import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from urllib.parse import urljoin
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials
import shutil

# === 配置 Google Drive ===
os.environ['HTTP_PROXY'] = 'http://127.0.0.1:7890'
os.environ['HTTPS_PROXY'] = 'http://127.0.0.1:7890'
SCOPES = ['https://www.googleapis.com/auth/drive.file']

ROOT_FOLDER_NAME = '气象数据'  # 根目录名称

def get_drive_service():
    creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    service = build('drive', 'v3', credentials=creds)
    return service

def upload_file_to_drive(local_file, parent_folder_id=None):
    service = get_drive_service()
    file_metadata = {'name': os.path.basename(local_file)}
    if parent_folder_id:
        file_metadata['parents'] = [parent_folder_id]
    media = MediaFileUpload(local_file, resumable=True)
    file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
    print(f"☁️ 上传完成: {local_file}, Drive ID: {file.get('id')}")

# === 区域页面 URL ===
region_urls = {
    "IX_Pakistan": "https://wwmiws.wmo.int/index.php/metareas/display/9",
    "VIII_N_India": "https://wwmiws.wmo.int/index.php/metareas/display/8N",
    "VIII_S_Mauritius_LaReunion": "https://wwmiws.wmo.int/index.php/metareas/display/8S",
}

# === 本地保存目录 ===
base_dir = "downloads"
today = datetime.now().strftime("%Y-%m-%d")
os.makedirs(base_dir, exist_ok=True)

log_path = os.path.join(base_dir, "download_log.txt")

def log(message: str):
    with open(log_path, "a", encoding="utf-8") as logf:
        logf.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}\n")
    print(message)

log("=== 🕒 启动自动下载任务 ===")

for region, page_url in region_urls.items():
    log(f"\n🔍 开始抓取 {region}: {page_url}")
    try:
        resp = requests.get(page_url, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        log(f"❌ 无法访问 {page_url}: {e}")
        continue

    soup = BeautifulSoup(resp.text, "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        title = a.get("title", "").lower()
        if "download" in href.lower() or "bulletin_download" in href.lower() or ".txt" in title:
            links.append(urljoin(page_url, href))

    if not links:
        log(f"⚠️ 未找到下载链接")
        continue

    # 本地目录
    region_dir = os.path.join(base_dir, ROOT_FOLDER_NAME, today, region)
    os.makedirs(region_dir, exist_ok=True)

    for file_url in links:
        try:
            file_resp = requests.get(file_url, timeout=60)
            file_resp.raise_for_status()

            filename = os.path.basename(file_url.rstrip("/"))
            cd = file_resp.headers.get("Content-Disposition", "")
            match = re.search(r'filename="?([^"]+)"?', cd)
            if match:
                filename = match.group(1)

            save_path = os.path.join(region_dir, filename)
            if os.path.exists(save_path):
                log(f"⏭️ 已存在，跳过: {filename}")
                continue

            with open(save_path, "wb") as f:
                f.write(file_resp.content)
            log(f"✅ 下载完成: {filename}")

            # 上传 Google Drive
            try:
                service = get_drive_service()

                # 根文件夹（气象数据）
                query = f"name='{ROOT_FOLDER_NAME}' and trashed=false"
                results = service.files().list(q=query, fields="files(id, name)").execute()
                files = results.get('files', [])
                if files:
                    root_folder_id = files[0]['id']
                else:
                    file_metadata = {'name': ROOT_FOLDER_NAME, 'mimeType': 'application/vnd.google-apps.folder'}
                    root_folder_id = service.files().create(body=file_metadata, fields='id').execute()['id']

                # 日期文件夹
                query = f"name='{today}' and '{root_folder_id}' in parents and trashed=false"
                results = service.files().list(q=query, fields="files(id, name)").execute()
                files = results.get('files', [])
                if files:
                    day_folder_id = files[0]['id']
                else:
                    file_metadata = {'name': today, 'mimeType': 'application/vnd.google-apps.folder', 'parents':[root_folder_id]}
                    day_folder_id = service.files().create(body=file_metadata, fields='id').execute()['id']

                # 区域子文件夹
                query = f"name='{region}' and '{day_folder_id}' in parents and trashed=false"
                results = service.files().list(q=query, fields="files(id, name)").execute()
                files = results.get('files', [])
                if files:
                    region_folder_id = files[0]['id']
                else:
                    file_metadata = {'name': region, 'mimeType': 'application/vnd.google-apps.folder', 'parents':[day_folder_id]}
                    region_folder_id = service.files().create(body=file_metadata, fields='id').execute()['id']

                # 上传文件
                upload_file_to_drive(save_path, region_folder_id)
                os.remove(save_path)
            except Exception as e:
                log(f"❌ 上传失败: {filename} ({e})")

        except Exception as e:
            log(f"❌ 下载失败: {file_url} ({e})")

# 上传日志文件
try:
    upload_file_to_drive(log_path)
    os.remove(log_path)
except Exception as e:
    log(f"❌ 日志上传失败: {e}")

# 删除空目录
try:
    day_dir = os.path.join(base_dir, ROOT_FOLDER_NAME, today)
    if os.path.exists(day_dir) and not os.listdir(day_dir):
        shutil.rmtree(day_dir)
except Exception as e:
    log(f"❌ 删除目录失败: {e}")

log("\n=== ✅ 本次任务执行完毕 ===\n")