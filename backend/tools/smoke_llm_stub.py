"""冒烟用的最小 OpenAI 兼容桩服务：按提示词返回合法的打分 JSON 或建议 JSON。

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

# 第 3 条的 original 故意写成简历里没有的表述，用来验证定位校验会追加 honesty_warnings
SUGGESTION = {
    "suggestions": [
        {
            "section": "work[0].highlights",
            "action": "改写",
            "original": "订单系统",
            "proposed": "负责订单系统重构，支撑日均百万订单，接口 P99 降到 120ms",
            "why": "岗位强调高并发交易系统与性能优化",
            "priority": "high",
        },
        {
            "section": "skills",
            "action": "补充关键词",
            "original": "",
            "proposed": "如有 Kafka 实际使用经验请补充说明（消息队列、削峰填谷）",
            "why": "岗位把 Kafka 列为硬性要求",
            "priority": "medium",
        },
        {
            "section": "projects[0].highlights",
            "action": "改写",
            "original": "主导过亿级用户增长项目",
            "proposed": "主导过亿级用户增长项目",
            "why": "测试定位失败路径",
            "priority": "low",
        },
    ],
    "missing_keywords": ["Kafka", "Kubernetes"],
    "honesty_warnings": ["岗位要求 Kafka，简历没有对应证据，不得虚构"],
}


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode("utf-8", "ignore")
        payload = SUGGESTION if "修改建议" in raw or "简历顾问" in raw else SCORE
        body = json.dumps(
            {
                "id": "chatcmpl-stub",
                "object": "chat.completion",
                "created": 0,
                "model": "stub-model",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": json.dumps(payload, ensure_ascii=False)},
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
