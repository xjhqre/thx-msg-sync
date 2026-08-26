import os
import json
import time
import hashlib
import logging

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# 配置项（可通过环境变量覆盖，便于部署）
TARGET_URL = os.environ.get("TARGET_URL",
                            "https://t.10jqka.com.cn/lgt/user_page/?user_code=10rrj9qxiaa7bbdcddfed3#/")
WECHAT_WEBHOOK_URL = os.environ.get("WECHAT_WEBHOOK_URL", "YOUR_WECHAT_WEBHOOK_URL")
CHECK_INTERVAL = float(os.environ.get("CHECK_INTERVAL", "5"))
# 持久化文件（记录上次处理到哪条动态，重启后不会重复推送）
STATE_FILE = os.environ.get("STATE_FILE", os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json"))

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
}


def stable_id(content, post=None):
    """生成跨进程稳定的去重 ID：优先 data-* 属性，兜底用内容哈希。"""
    if post is not None:
        data_id = post.get('data-y') or post.get('data-id')
        if data_id:
            return str(data_id)
    # 使用内容哈希保证稳定性（Python 内置 hash() 每次运行会随机化）
    return hashlib.sha256(content.encode('utf-8')).hexdigest()


def fetch_page(url, session):
    """请求页面并返回明文/None，带简单健壮性。"""
    response = session.get(url, timeout=10)
    response.raise_for_status()
    return response.text


def parse_posts(html, last_post_id):
    """解析页面，返回 (id, content) 列表。页面按时间倒序，遇旧动态即停止。"""
    soup = BeautifulSoup(html, 'html.parser')
    new_posts = []
    for post in soup.find_all('div', class_='post_item'):
        content_div = post.find('div', class_='abstract-content')
        if not content_div:
            continue
        content = content_div.get_text(strip=True)
        if not content:  # 过滤空内容
            continue
        post_id = stable_id(content, post)
        if post_id == last_post_id:
            break  # 动态按时间倒序排列，遇到旧的就停止
        new_posts.append((post_id, content))
    return new_posts


def fetch_user_posts(url, last_post_id, session):
    """抓取并返回新动态 [(id, content), ...]，失败返回 []。"""
    try:
        html = fetch_page(url, session)
        return parse_posts(html, last_post_id)
    except Exception as e:
        logging.error(f"爬取失败: {e}")
        return []


def send_wechat_notification(content, session):
    """发送企业微信机器人通知。"""
    data = {
        "msgtype": "text",
        "text": {"content": content}
    }
    try:
        response = session.post(WECHAT_WEBHOOK_URL, json=data, timeout=10)
        if response.status_code == 200:
            logging.info("微信通知发送成功")
        else:
            logging.error(f"微信通知发送失败: {response.status_code}")
    except Exception as e:
        logging.error(f"微信通知发送异常: {e}")


def build_session():
    """复用连接并支持网络重试，减少握手开销与单次抖动导致的漏检。"""
    session = requests.Session()
    session.headers.update(HEADERS)
    retry = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def load_state():
    """从磁盘加载上次记录的动态 ID，无记录时返回空字符串。"""
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("last_post_id", "")
    except (FileNotFoundError, json.JSONDecodeError):
        return ""


def save_state(last_post_id):
    """把最新动态 ID 原子写入磁盘，避免中途崩溃破坏文件。"""
    tmp_file = STATE_FILE + ".tmp"
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump({"last_post_id": last_post_id}, f, ensure_ascii=False)
    os.replace(tmp_file, STATE_FILE)  # 原子替换


def main():
    session = build_session()
    last_post_id = load_state()  # 从持久化文件恢复上次进度

    while True:
        new_posts = fetch_user_posts(TARGET_URL, last_post_id, session)
        # if new_posts:
        #     logging.info(f"发现 {len(new_posts)} 条新动态")
        #     for _, content in new_posts:
        #         send_wechat_notification(f"【新动态】\n{content}", session)
        #     # 更新为最新一条动态的稳定 ID，并持久化
        #     last_post_id = new_posts[0][0]
        #     save_state(last_post_id)
        # else:
        #     logging.info("无新动态")

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()