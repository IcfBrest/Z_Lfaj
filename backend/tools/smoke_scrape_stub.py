"""冒烟用的招聘站点桩：同时扮演米哈游 ATS 与腾讯招聘的公开接口。

只为本机端到端联调用，不参与生产路径。启动方式：
    python tools/smoke_scrape_stub.py            # 默认 127.0.0.1:8097
配合环境变量：
    MIHOYO_BASE_URL=http://127.0.0.1:8097/mihoyo
    TENCENT_BASE_URL=http://127.0.0.1:8097/tencent
"""

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

MIHOYO_JOBS = [
    {
        "id": "7001",
        "title": "服务端开发工程师（原神）",
        "addressDetailList": [{"addressDetail": "上海"}],
        "competencyType": "程序技术",
        "jobNature": "全职",
        "tagList": ["Go", "Redis"],
        "jobSummary": "负责游戏服务端。",
    },
    {
        "id": "7002",
        "title": "客户端开发工程师（原神）",
        "addressDetailList": [{"addressDetail": "上海"}, {"addressDetail": "新加坡"}],
        "competencyType": "程序技术",
        "jobNature": "全职",
        "tagList": ["C++", "Unity"],
        "jobSummary": "负责客户端玩法。",
    },
    {
        "id": "7003",
        "title": "游戏运营（崩坏）",
        "addressDetailList": [{"addressDetail": "上海"}],
        "competencyType": "运营",
        "jobNature": "全职",
        "tagList": [],
        "jobSummary": "负责版本运营。",
    },
]

MIHOYO_DETAILS = {
    "7001": {
        "id": "7001",
        "title": "服务端开发工程师（原神）",
        "description": "1、负责服务端框架与模块开发；\n2、参与性能优化。",
        "jobRequire": "1、本科及以上学历；\n2、三年以上 C++/Go 开发经验。",
        "addition": "有 MMO 经验者优先。",
    },
    "7002": {
        "id": "7002",
        "title": "客户端开发工程师（原神）",
        "description": "1、负责客户端玩法系统开发。",
        "jobRequire": "1、熟悉 C++ 与 Unity；\n2、两年以上游戏开发经验。",
        "addition": "",
    },
    "7003": {
        "id": "7003",
        "title": "游戏运营（崩坏）",
        "description": "1、负责版本活动设计与投放。",
        "jobRequire": "1、有二次元游戏运营经验。",
        "addition": "",
    },
}

TENCENT_JOBS = [
    {
        "PostId": "9001",
        "RecruitPostName": "后台开发工程师（腾讯云）",
        "LocationName": "深圳",
        "BGName": "CSIG",
        "CategoryName": "技术",
        "Responsibility": "负责云平台后台服务开发；",
        "RequireWorkYearsName": "三年以上工作经验",
        "PostURL": "http://careers.tencent.com/jobdesc.html?postId=9001",
        "LastUpdateTime": "2026-11-01 10:00:00",
    },
    {
        "PostId": "9002",
        "RecruitPostName": "前端开发工程师（微信）",
        "LocationName": "广州",
        "BGName": "WXG",
        "CategoryName": "技术",
        "Responsibility": "负责微信前端页面开发；",
        "RequireWorkYearsName": "不限",
        "PostURL": "http://careers.tencent.com/jobdesc.html?postId=9002",
        "LastUpdateTime": "2026-11-02 09:00:00",
    },
]

TENCENT_DETAILS = {
    "9001": {
        "PostId": "9001",
        "Requirement": "1、熟悉 C++ 或 Go；\n2、有高并发系统经验。",
        "Responsibility": "负责云平台后台服务开发；",
        "PostURL": "http://careers.tencent.com/jobdesc.html?postId=9001",
    },
    "9002": {
        "PostId": "9002",
        "Requirement": "1、熟悉 Vue/React；\n2、有大型前端项目经验。",
        "Responsibility": "负责微信前端页面开发；",
        "PostURL": "http://careers.tencent.com/jobdesc.html?postId=9002",
    },
}


def _json(handler: BaseHTTPRequestHandler, payload: dict, status: int = 200) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if parsed.path == "/health":
            _json(self, {"status": "ok"})
        elif parsed.path == "/tencent/post/Query":
            page = int((query.get("pageIndex") or ["1"])[0])
            posts = TENCENT_JOBS if page == 1 else []
            _json(self, {"Code": 200, "Data": {"Count": len(TENCENT_JOBS), "Posts": posts}})
        elif parsed.path == "/tencent/post/ByPostId":
            post_id = (query.get("postId") or [""])[0]
            if post_id not in TENCENT_DETAILS:
                _json(self, {"Code": 404, "Message": "post not found"}, status=200)
                return
            _json(self, {"Code": 200, "Data": TENCENT_DETAILS[post_id]})
        else:
            _json(self, {"Code": 404, "Message": "unknown path"}, status=404)

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode("utf-8", "ignore")
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = {}
        if self.path == "/mihoyo/ats-portal/v1/job/list":
            page = int(payload.get("pageNo") or 1)
            items = MIHOYO_JOBS if page == 1 else []
            _json(self, {"success": True, "data": {"list": items, "total": len(MIHOYO_JOBS)}})
        elif self.path == "/mihoyo/ats-portal/v1/job/info":
            job_id = str(payload.get("id") or "")
            if job_id not in MIHOYO_DETAILS:
                _json(self, {"success": False, "message": "职位不存在", "code": 404})
                return
            _json(self, {"success": True, "data": MIHOYO_DETAILS[job_id]})
        else:
            _json(self, {"success": False, "message": "unknown path"}, status=404)

    def log_message(self, fmt, *args):  # 静默
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8097
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
