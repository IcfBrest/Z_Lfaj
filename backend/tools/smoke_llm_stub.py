"""冒烟用的最小 OpenAI 兼容桩服务：固定返回一份合法的打分 JSON。

只为本机端到端联调用，不参与生产路径。
"""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SCORE = {
    "dimension_scores": {"技能匹配": 80, "经验相关度": 70, "职级与薪资匹配": 60, "行业/业务匹配": 50},
    "verdict": "匹配良好",
    "reasons": "技能与岗位基本吻合，年限略低。",
    "matching_points": ["Python/MySQL 命中岗位要求"],
    "gaps": ["缺少 Kafka 实战"],
    "score_basis": "四维均等加权",
}


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        body = json.dumps(
            {
                "id": "chatcmpl-stub",
                "object": "chat.completion",
                "created": 0,
                "model": "stub-model",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": json.dumps(SCORE, ensure_ascii=False)},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 1200, "completion_tokens": 180, "total_tokens": 1380},
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):  # 静默
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 8099), Handler).serve_forever()
