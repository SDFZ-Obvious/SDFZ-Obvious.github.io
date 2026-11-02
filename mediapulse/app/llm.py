"""Optional DeepSeek narrative summary. All rules work without it."""
from __future__ import annotations

import json
import logging
from typing import Any

from .http_client import HttpClient

log = logging.getLogger("mediapulse.llm")

SYSTEM = (
    "你是一名资深的自媒体运营分析师。你会收到一个创作者账号的结构化数据摘要。"
    "请只依据数据写一段 280-450 字的中文运营结论，包含：本周期最重要的变化、"
    "一条最值得复制的增长动作、一条最优先修复的风险、以及未来两周的具体行动。"
    "不要编造数据中没有的数字，不要使用空泛的套话，不要输出 Markdown 标题。"
)


def deepseek_summary(store, account: dict[str, Any], dashboard: dict[str, Any],
                     video_table: dict[str, Any]) -> tuple[str, str]:
    settings = store.settings()
    if settings.get("llm_enabled") != "1":
        return "", ""
    key = (settings.get("deepseek_api_key") or "").strip()
    if not key:
        return "", "未配置 DeepSeek API Key"
    payload = {
        "account": {"name": account.get("name"), "platform": account.get("platform")},
        "period": dashboard.get("period"),
        "kpis": [{k: v for k, v in item.items() if k in ("label", "value", "unit", "delta")}
                 for item in dashboard.get("kpis", [])],
        "health": dashboard.get("health"),
        "best_slots": dashboard.get("best_slots", [])[:3],
        "duration": dashboard.get("duration", []),
        "top_videos": [{k: v for k, v in item.items()
                        if k in ("title", "period_views", "engagement_rate", "conversion", "duration")}
                       for item in video_table.get("videos", [])[:10]],
        "insights": [{k: v for k, v in item.items() if k in ("severity", "title", "body", "action")}
                     for item in dashboard.get("insights", [])[:8]],
        "traffic_sources": dashboard.get("sources", [])[:6],
        "cadence": dashboard.get("cadence"),
        "retention_source": dashboard.get("retention_source"),
    }
    body = {
        "model": settings.get("deepseek_model", "deepseek-chat") or "deepseek-chat",
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        "temperature": 0.5,
        "max_tokens": 900,
        "stream": False,
    }
    try:
        client = HttpClient(headers={"Authorization": f"Bearer {key}"})
        data = client.request(
            "https://api.deepseek.com/chat/completions",
            method="POST", json_body=body, timeout=45, retries=1,
        )
        choices = data.get("choices") or []
        text = (choices[0].get("message") or {}).get("content", "") if choices else ""
        if not text:
            return "", data.get("error", {}).get("message", "AI 返回为空")
        return text.strip(), ""
    except Exception as exc:
        log.warning("deepseek summary failed: %s", exc)
        return "", f"AI 摘要生成失败：{str(exc)[:200]}"
