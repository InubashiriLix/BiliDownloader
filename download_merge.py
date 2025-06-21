import os
import re
import requests
from tqdm import tqdm
import ffmpeg
import shlex

from session import session  # 你的登录 session


def download_video(bvid: str, title: str, video_url: str) -> str:
    """
    带进度条的分块下载视频
    """
    out_dir = "temp"
    os.makedirs(out_dir, exist_ok=True)
    safe_title = _sanitize_filename(title)
    path = os.path.join(out_dir, f"{safe_title}_video_only.mp4")

    headers = {
        "Referer": f"https://www.bilibili.com/video/{bvid}",
        "User-Agent": session.headers.get("User-Agent"),
    }

    # 先发 HEAD 请求拿 Content-Length
    total = int(
        session.head(video_url, headers=headers).headers.get("Content-Length", 0)
    )

    with session.get(video_url, headers=headers, stream=True) as resp:
        resp.raise_for_status()
        with (
            open(path, "wb") as f,
            tqdm(
                total=total,
                unit="B",
                unit_scale=True,
                unit_divisor=1024,
                desc=f"下载视频 {safe_title}",
            ) as pbar,
        ):
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                f.write(chunk)
                pbar.update(len(chunk))

    print(f"\n✅ 视频已保存到 {path}")
    return path


def download_audio(bvid: str, title: str, audio_url: str) -> str:
    """
    带进度条的分块下载音频
    """
    out_dir = "temp"
    os.makedirs(out_dir, exist_ok=True)
    safe_title = _sanitize_filename(title)
    path = os.path.join(out_dir, f"{safe_title}_audio_only.mp3")

    headers = {
        "Referer": f"https://www.bilibili.com/video/{bvid}",
        "User-Agent": session.headers.get("User-Agent"),
    }

    total = int(
        session.head(audio_url, headers=headers).headers.get("Content-Length", 0)
    )

    with session.get(audio_url, headers=headers, stream=True) as resp:
        resp.raise_for_status()
        with (
            open(path, "wb") as f,
            tqdm(
                total=total,
                unit="B",
                unit_scale=True,
                unit_divisor=1024,
                desc=f"下载音频 {safe_title}",
            ) as pbar,
        ):
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                f.write(chunk)
                pbar.update(len(chunk))

    print(f"\n✅ 音频已保存到 {path}")
    return path


def _sanitize_filename(name: str) -> str:
    # Windows 下非法字符：\/:*?"<>| 另外我们把 / 也替换掉
    return re.sub(r'[\\/:*?"<>|]', "_", name)


def merge(name: str, av_path: str, audio_path: str, out_dir_path: str):
    """
    用 ffmpeg-python 合并视频和音频
    """
    # 1) 确保输出目录存在
    os.makedirs(out_dir_path, exist_ok=True)

    # 2) 清理文件名
    safe_name = _sanitize_filename(name)
    out_path = os.path.join(out_dir_path, f"{safe_name}.mp4")

    # 3) 准备两个输入流
    video = ffmpeg.input(av_path)
    audio = ffmpeg.input(audio_path)

    # 4) 执行合并，capture stderr 方便调试
    try:
        (
            ffmpeg.output(video, audio, out_path, vcodec="copy", acodec="copy")
            .overwrite_output()
            .run(capture_stdout=True, capture_stderr=True)
        )
        print(f"✅ 合并成功：{out_path}")
        os.remove(av_path)  # 删除临时视频文件
        os.remove(audio_path)  # 删除临时音频文件
    except ffmpeg.Error as e:
        # 如果 stderr 有内容，就解码，否则直接打印异常信息
        err = None
        if getattr(e, "stderr", None):
            err = e.stderr.decode("utf-8", errors="ignore")
        print("❌ FFmpeg 合并失败：")
        if err:
            print(err)
        else:
            print(e)
