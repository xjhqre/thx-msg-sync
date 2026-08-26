import os
import time
import json
import logging
import requests
from typing import List, Dict, Any

# ---------- 配置 ----------
USER_CODE = "10rrj9qxiaa7bbdcddfed3"          # 要监控的用户 code
INTERVAL = 5                                   # 轮询间隔（秒）
WECHAT_WEBHOOK = os.environ.get("WECHAT_WEBHOOK_URL")  # 企业微信机器人 Webhook 地址
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")  # 持久化上次处理的最新动态 ID

# 日志设置
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# ---------- 请求函数 ----------
def fetch_user_contents(user_code: str) -> List[Dict[str, Any]]:
    """
    调用同花顺接口，获取用户动态列表
    返回 contents 列表，若失败返回空列表
    """
    url = "https://t.10jqka.com.cn/user_center/open/api/content/v2/get_by_uid"
    headers = {
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Cache-Control": "max-age=0",
        "Connection": "keep-alive",
        "Content-Type": "application/json",
        "Origin": "https://t.10jqka.com.cn",
        "Referer": f"https://t.10jqka.com.cn/lgt/user_page/?user_code={user_code}",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
        "hexin-v": "BCOqHPlqnpHaapyW9YvDmHQBzAWtAHgAlwC6ANEADADbDkoANfwYA6AAZwOe",  # 可能需要定期更新
        "sec-ch-ua": '"Chromium";v="134", "Not:A-Brand";v="24", "Google Chrome";v="134"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
    }
    payload = {"user_code": user_code}

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status_code") != 0:
            logger.error(f"接口返回异常: {data.get('status_code')} - {data.get('status_msg')}")
            return []
        # 实际返回结构为嵌套在 data 下的 contents 列表
        contents = data.get("data", {}).get("contents", [])
        logger.info(f"请求成功，获取到 {len(contents)} 条动态")
        return contents
    except Exception as e:
        logger.error(f"请求失败: {e}")
        return []

# ---------- 微信推送 ----------
def send_to_wechat(content: str) -> None:
    """通过企业微信机器人发送消息"""
    if not WECHAT_WEBHOOK:
        logger.warning("未设置 WECHAT_WEBHOOK_URL，无法发送微信，仅打印内容")
        logger.info(f"新动态内容:\n{content}")
        return

    # 企业微信限制消息长度，若太长可截断
    if len(content) > 2000:
        content = content[:2000] + "...(截断)"

    data = {
        "msgtype": "text",
        "text": {"content": content}
    }
    try:
        resp = requests.post(WECHAT_WEBHOOK, json=data, timeout=5)
        if resp.status_code == 200:
            logger.info("微信推送成功")
        else:
            logger.error(f"微信推送失败，状态码: {resp.status_code}, 响应: {resp.text}")
    except Exception as e:
        logger.error(f"微信推送异常: {e}")

# ---------- 持久化存储 ----------
def load_last_id() -> str:
    """从磁盘加载上次处理的最新动态 ID，无记录或损坏时返回空串。"""
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f).get("last_id", "")
    except (FileNotFoundError, json.JSONDecodeError):
        return ""


def save_last_id(post_id: str) -> None:
    """原子写入最新动态 ID，避免中途崩溃破坏文件。"""
    tmp_file = STATE_FILE + ".tmp"
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump({"last_id": post_id}, f, ensure_ascii=False)
    os.replace(tmp_file, STATE_FILE)


# ---------- 主循环 ----------
def main():
    last_id = load_last_id()   # 从持久化文件恢复上次进度
    logger.info(f"开始监控用户 {USER_CODE}，间隔 {INTERVAL} 秒，上次动态 ID: {last_id or '无'}")

    while True:
        try:
            contents = fetch_user_contents(USER_CODE)
            if not contents:
                time.sleep(INTERVAL)
                continue

            # 接口返回的最新动态在前，因此只取第一条
            item = contents[0]
            info = item.get("info", {})
            post_id = info.get("id")
            if not post_id:
                logger.warning("未获取到动态 ID，跳过本轮")
                time.sleep(INTERVAL)
                continue

            if post_id == last_id:
                logger.debug(f"无新动态，最新 ID: {post_id}")
            else:
                abstract = item.get("abstract", {})
                content_text = abstract.get("content", "")
                logger.info(f"最新动态内容: {content_text}")
                if content_text:
                    # send_to_wechat(content_text)
                    logger.info(f"发现并处理新动态，ID: {post_id}")
                else:
                    logger.warning(f"动态 {post_id} 无内容，已记录 ID 去重")

                # 无论是否有内容都更新最新 ID，避免重复处理
                last_id = post_id
                save_last_id(post_id)

        except Exception as e:
            logger.error(f"主循环异常: {e}")

        time.sleep(INTERVAL)

if __name__ == "__main__":
    main()