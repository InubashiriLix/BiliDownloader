from login import login
from utils import get_bv_info, extract_bv
from download_merge import download_video, download_audio, merge


if __name__ == "__main__":
    infos = login("data/login_info.json")

    bvid: str | None = "shit"
    bvid = extract_bv(input("enter url: "))
    if bvid is None:
        print("invalid url, parse failed")
        exit(1)

    bv_info = get_bv_info(
        bvid,
        infos["SESSDATA"]["value"],
        infos["bili_jct"]["value"],
        infos["DedeUserID"]["value"],
    )

    v_path: str = download_video(**bv_info["get_video_infos"]())
    a_path: str = download_audio(**bv_info["get_audio_infos"]())

    merge(bv_info["title"], av_path=v_path, audio_path=a_path, out_dir_path="output")
