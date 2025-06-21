from typing import Any, Optional
import os
import time
import qrcode
from datetime import datetime, timezone
import json

from session import session


def get_qr_login() -> tuple[str, str]:
    """
    1) 调用新版接口申请二维码 (30s 内有效，官方说 180s 过期)
    返回 (qrcode_key, qr_url)
    """
    url = "https://passport.bilibili.com/x/passport-login/web/qrcode/generate"
    resp = session.get(url, timeout=5)
    resp.raise_for_status()
    js = resp.json()
    if js["code"] != 0:
        raise RuntimeError(f"申请二维码失败: {js}")
    data = js["data"]
    return data["qrcode_key"], data["url"]


def show_qr_terminal(qr_url: str) -> None:
    """
    在终端直接打印二维码
    """
    qr = qrcode.QRCode(box_size=1, border=1)
    qr.add_data(qr_url)
    qr.make(fit=True)
    qr.print_ascii(invert=True)


def poll_login(qrcode_key: str, interval: float = 2, timeout: float = 180) -> bool:
    """
    2) 轮询扫码结果
      - 返回 True：登录成功（已写入 Cookie）
      - 返回 False：二维码过期，需要重新申请
      - 抛出 TimeoutError：超时未扫码
      - 抛出 RuntimeError：其他异常
    """
    poll_url = "https://passport.bilibili.com/x/passport-login/web/qrcode/poll"
    params = {"qrcode_key": qrcode_key}
    start = time.time()

    while True:
        resp = session.get(poll_url, params=params, timeout=5)
        resp.raise_for_status()
        js = resp.json()
        # http-level code
        if js["code"] != 0:
            raise RuntimeError(f"轮询接口异常: {js}")

        d = js["data"]
        status = d["code"]  # 86101 / 86090 / 86038 / 0
        elapsed = int(time.time() - start)

        if status == 86101:
            msg = "未扫码"
        elif status == 86090:
            msg = "已扫码，待确认"
        elif status == 86038:
            print(f"\n⚠️ [ {elapsed}s ] 二维码已过期，重新申请...\n")
            return False
        elif status == 0:
            # 登录成功，写入 Cookie
            login_url = d["url"]
            session.get(login_url, timeout=5)
            print(f"\n✅ 登录成功！[{elapsed}s]\n")
            return True
        else:
            raise RuntimeError(f"未知扫码状态: {js}")

        # 覆盖同一行实时打印
        print(f"\r[{elapsed:>3}s] {msg}", end="", flush=True)

        if elapsed >= timeout:
            raise TimeoutError("扫码登录超时")
        time.sleep(interval)


def extract_login_cookies_with_expiry(session):
    """
    提取 SESSDATA / bili_jct / DedeUserID 三个 Cookie 的值和过期时间。
    返回形如：
    顺便，一般六个月过期
    {
      "SESSDATA":   {"value": "...", "expires": "2025-07-12 08:23:45 UTC"},
      "bili_jct":   {"value": "...", "expires": "2025-07-12 08:23:45 UTC"},
      "DedeUserID": {"value": "...", "expires": "2025-07-12 08:23:45 UTC"},
    }
    """
    result = {}
    for name in ("SESSDATA", "bili_jct", "DedeUserID"):
        # 找到第一个匹配主站域名的 Cookie
        cookie = next(
            (
                c
                for c in session.cookies
                if c.name == name and c.domain.endswith(".bilibili.com")
            ),
            None,
        )
        if not cookie:
            result[name] = {"value": None, "expires": None}
            continue

        # 过期时间
        if cookie.expires is None:
            exp_str = None  # 会话级 Cookie，无明确过期时间
        else:
            dt = datetime.fromtimestamp(cookie.expires, tz=timezone.utc)
            exp_str = dt.strftime("%Y-%m-%d %H:%M:%S UTC")

        result[name] = {"value": cookie.value, "expires": exp_str}
    return result


def parse_login_info(file_path: str) -> dict[str, Any] | None:
    try:
        with open(file_path, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"登录信息文件 {file_path} 不存在，开始新登录流程。")
        return None


def parse_utc(dt_str: str) -> datetime:
    """
    Parse an ISO 8601 datetime string to a timezone-aware UTC datetime object.
    """
    return datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S %Z").replace(
        tzinfo=timezone.utc
    )


def login(file_path: str) -> dict[str, Any]:
    """
    主流程：检查本地缓存 → (未过期则直接加载到 session) → 否则走二维码登录流程 → 写回文件 → 返回 cookie info
    """
    os.makedirs("data", exist_ok=True)
    temp_info = parse_login_info(file_path)
    if temp_info:
        try:
            now = datetime.now(timezone.utc)
            all_ok = all(
                parse_utc(temp_info[name]["expires"]) > now
                for name in ("SESSDATA", "bili_jct", "DedeUserID")
                if temp_info[name]["expires"] is not None
            )
            if all_ok:
                session.cookies.update(
                    {
                        "SESSDATA": temp_info["SESSDATA"]["value"],
                        "bili_jct": temp_info["bili_jct"]["value"],
                        "DedeUserID": temp_info["DedeUserID"]["value"],
                    }
                )
                print("✅ 已加载本地缓存，Cookie 未过期，直接使用。")
                return temp_info
        except Exception:
            print("⚠️ 本地缓存无效或已过期，重新登录。")

    while True:
        key, url = get_qr_login()
        print("请用哔哩哔哩 App 扫描下面二维码：\n")
        show_qr_terminal(url)
        try:
            if poll_login(key):
                break
        except TimeoutError:
            print("\n⏰ 扫码超时，重新获取...\n")
        except Exception as e:
            print(f"\n❌ 登录异常：{e}，程序退出。")
            exit(1)

    info = extract_login_cookies_with_expiry(session)
    print("—— 登录态 Cookie 信息 ——")
    for k, v in info.items():
        print(f"{k:10s}= {v['value']}\n  expires: {v['expires']}")

    # 4. 写回文件
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=2)

    return info


if __name__ == "__main__":
    login("data/login_info.json")
