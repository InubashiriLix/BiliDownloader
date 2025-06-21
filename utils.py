from typing import Any, List, Dict, Optional
import requests
import json
import re
from requests.exceptions import SSLError, RequestException
from urllib3.exceptions import MaxRetryError

from cus_exceptions import AidRetrievalError, CidRetrievalError, VideoNotFoundError
from login import session


def _get_header(
    bvid: str, sess_data: str, bili_jct: str, dede_user_id: str
) -> dict[str, Any]:
    """
    构造带登录态的 header，包含你完整复制的所有 Cookie。
    """
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/114.0.0.0 Safari/537.36"
        ),
        "Referer": f"https://www.bilibili.com/video/{bvid}?p=1",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Cookie": (
            "enable_web_push=DISABLE; "
            "buvid4=8304DBFC-7EF8-F9BC-14F7-9DDAC80DA37954307-023100511-VdSZDbI3OC7ZiyoQAwmACA%3D%3D; "
            "buvid_fp_plain=undefined; "
            "is-2022-channel=1; "
            "CURRENT_BLACKGAP=0; "
            f"DedeUserID={dede_user_id}; "
            "DedeUserID__ckMd5=431600431a432e63; "
            f"SESSDATA={sess_data}; "
            f"bili_jct={bili_jct}; "
            "enable_feed_channel=ENABLE; "
            "_uuid=15D52EE9-1A15-71FD-FF1F-2E336273715339217infoc; "
            "hit-dyn-v2=1; "
            "rpdid=|(J~Rllk~)l)0J'u~RY||R~Yu; "
            "buvid3=8712A290-56E3-42C4-0688-CCB63730A5DC91931infoc; "
            "b_nut=1746111291; "
            "CURRENT_QUALITY=80; "
            "header_theme_version=OPEN; "
            "theme-tip-show=SHOWED; "
            "theme-avatar-tip-show=SHOWED; "
            "LIVE_BUVID=AUTO9017478208868957; "
            "fingerprint=7615b2448e54a09b1ee3944d4ae6049f; "
            "buvid_fp=3bd278045d8390e6de887c297b5af287; "
            "PVID=3; "
            "bili_ticket=eyJhbGciOiJIUzI1NiIsImtpZCI6InMwMyIsInR5cCI6IkpXVCJ9."
            "eyJleHAiOjE3NTA2NTgwMDEsImlhdCI6MTc1MDM5ODc0MSwicGx0IjotMX0."
            "_H3OF9LHybLT1V4prpKJLDKeTs4wsbhHUSlb-XoM-is; "
            "bili_ticket_expires=1750657941; "
            "home_feed_column=5; "
            "browser_resolution=1659-811; "
            "sid=6pat9nc9; "
            "CURRENT_FNVAL=4048; "
            "b_lsid=1071EB3C9_197927897F6; "
            "bp_t_offset_183894189=1080935962940276736"
        ),
    }


def get_aid_cid(bvid: str) -> tuple[int, int]:
    """
    通过 web-interface/view 接口拿 aid, cid
    """
    url = "https://api.bilibili.com/x/web-interface/view"
    resp = requests.get(
        url, params={"bvid": bvid}, headers={"User-Agent": "Mozilla/5.0"}, timeout=5
    )
    resp.raise_for_status()
    js = resp.json()
    data = js.get("data", {})
    aid = data.get("aid")
    cid = data.get("cid")

    if aid is None:
        raise AidRetrievalError("获取 aid 失败")
    if cid is None:
        raise CidRetrievalError("获取 cid 失败")

    return aid, cid


def _get_quality_list(
    bvid: str, sessdata: str, bili_jct: str, dede_user_id: str, headers: dict[str, Any]
) -> List[int]:
    """
    返回当前登录状态下可用的清晰度 qn 列表（从高到低）
    """
    # 先拿 aid 和 cid
    aid, cid = get_aid_cid(bvid)

    # 播放接口参数，按 injahow 实现的 web_api 逻辑拼装
    params = {
        "avid": aid,
        "bvid": bvid,
        "cid": cid,
        "otype": "json",  # JSON 格式返回
        # 以下字段决定 accept_quality 列表的完整性
        "type": "mp4",  # 请求 MP4 流
        "fnver": 0,  # 默认 fnver=0
        "fnval": 0,  # MP4 对应 fnval=0
        "fourk": 1,  # 开启 4K 支持
        "platform": "html5",  # MP4 需加 platform
        "high_quality": 1,  # MP4 需加 high_quality
    }

    resp = requests.get(
        "https://api.bilibili.com/x/player/playurl",
        headers=headers,
        params=params,
        timeout=5,
    )
    resp.raise_for_status()
    data = resp.json().get("data", {})

    return data.get("accept_quality", [])


def _safe_get(url: str, **kwargs) -> requests.Response:
    """
    三轮尝试：
      1) 普通 session.get（带 retry adapter）
      2) verify=False
      3) 不走 Retry adapter，直接 requests.get
    """
    # 先把 retry adapter 保留在 session 上
    try:
        resp = session.get(url, **kwargs)
        resp.raise_for_status()
        return resp
    except (SSLError, MaxRetryError, RequestException) as e1:
        # 1) SSL 错误或重试失败，尝试关闭验证
        try:
            resp = session.get(
                url, verify=False, **{k: v for k, v in kwargs.items() if k != "verify"}
            )
            resp.raise_for_status()
            return resp
        except (SSLError, MaxRetryError, RequestException) as e2:
            # 2) 再次失败，临时移除 retry adapter 再试一次
            no_retry = requests.Session()
            no_retry.headers.update(session.headers)
            try:
                resp = no_retry.get(
                    url,
                    verify=False,
                    **{k: v for k, v in kwargs.items() if k != "verify"},
                )
                resp.raise_for_status()
                return resp
            except Exception as e3:
                # 3) 三次都挂了，就包装抛出
                raise RuntimeError(
                    f"三次尝试均失败:\n"
                    f"1) 普通 session.get → {e1}\n"
                    f"2) session.get verify=False → {e2}\n"
                    f"3) plain requests.get → {e3}"
                )


def get_bv_info(
    bvid: str, sessdata: str, bili_jct: str, dede_user_id: str
) -> Dict[str, Any]:
    # 确保 session 带上这三条关键 Cookie
    session.cookies.update(
        {
            "SESSDATA": sessdata,
            "bili_jct": bili_jct,
            "DedeUserID": dede_user_id,
        }
    )

    # 1) 拿页面 HTML（同样用 _safe_get）
    page_url = f"https://www.bilibili.com/video/{bvid}"
    try:
        resp = _safe_get(page_url, timeout=10)
        html = resp.text
    except RequestException as e:
        raise RuntimeError(f"无法获取视频页面 HTML: {e}")

    # 2) 从 HTML 提取 playinfo
    m = re.search(r"window\.__playinfo__\s*=\s*({.+?})\s*</script>", html, re.S)
    if not m:
        raise RuntimeError("无法从 HTML 中提取 playinfo 数据")
    playinfo = json.loads(m.group(1))

    dash = playinfo.get("data", {}).get("dash", {})
    video_url = dash.get("video", [{}])[0].get("baseUrl")
    audio_url = dash.get("audio", [{}])[0].get("baseUrl")
    qualities = playinfo.get("data", {}).get("accept_quality", [])

    info_api = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
    try:
        info_resp = _safe_get(info_api, timeout=5)
        title = info_resp.json().get("data", {}).get("title", "")
    except RequestException as e:
        raise RuntimeError(f"无法获取视频信息: {e}")

    return {
        "title": title,
        "video_url": video_url,
        "audio_url": audio_url,
        "accept_quality": qualities,
        "get_video_infos": lambda: {
            "bvid": bvid,
            "title": title,
            "video_url": video_url,
        },
        "get_audio_infos": lambda: {
            "bvid": bvid,
            "title": title,
            "audio_url": audio_url,
        },
    }


def extract_bv(url: str) -> Optional[str]:
    m = re.search(r"(BV[0-9A-Za-z]{10,})", url)
    return m.group(1) if m else None
