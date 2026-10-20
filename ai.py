from __future__ import annotations

import json
import re
import urllib.request
from datetime import date

from parser import parse
from rules import clamp_priority


def _active_config(config: dict) -> dict:
    active_id = config.get("active_provider_id")
    provider = next((p for p in config.get("providers", []) if p.get("id") == active_id), None)
    if provider:
        return {**config, **provider}
    return config


def _endpoint(base: str) -> str:
    base = (base or "https://api.deepseek.com").rstrip("/")
    return base if base.endswith("/v1") else base + "/v1"


def _extract_json(text: str):
    clean = text.strip().replace("```json", "").replace("```", "").strip()
    try: return json.loads(clean)
    except Exception: pass
    array = re.search(r"\[[\s\S]*\]", clean)
    if array:
        try: return json.loads(array.group(0))
        except Exception: pass
    obj = re.search(r"\{[\s\S]*\}", clean)
    if obj:
        try: return json.loads(obj.group(0))
        except Exception: pass
    raise ValueError("AI 返回的内容不是合法 JSON")


def _request(messages: list[dict], cfg: dict, temperature=.2, timeout=20) -> str:
    body = json.dumps({"model": cfg.get("model", "deepseek-chat"), "messages": messages, "temperature": temperature}, ensure_ascii=False).encode()
    req = urllib.request.Request(_endpoint(cfg.get("base_url", "")) + "/chat/completions", data=body, headers={"Content-Type": "application/json", "Authorization": "Bearer " + str(cfg.get("api_key", ""))}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as response:
        data = json.loads(response.read().decode())
    return data["choices"][0]["message"]["content"]


def call_ai(text: str, config: dict, projects: list[str]):
    cfg = _active_config(config)
    project_names = [p.get("name") if isinstance(p, dict) else p for p in projects]
    review = any(w in text.lower() for w in ["审稿", "评审", "referee", "reviewer"])
    if not cfg.get("api_key") or (review and not config.get("allow_review_ai")):
        return parse(text, projects), "offline"
    system = f'''你是 SciPlan 的科研任务结构化助手。今天是 {date.today().isoformat()}。
把用户的随手记录拆成真正可执行的任务，只输出 JSON 数组，不要 markdown，不要解释。
每项必须包含 title（动宾短语，最多28字）、board（论文/课题/标书/杂事）、project（已有课题名或 null）、workstream（表型线/机制线/结构线/写作线/合作线或 null）、due（YYYY-MM-DD 或 null）、est_hours（0.5/1/2/4/8）、need_focus（true/false）、priority（1-4，1最紧急）、reason（引用原文线索，20字以内）、purpose（这件事要解决什么，短句）、success_criteria（完成后留下什么结果，短句）、prerequisite（需要等待什么，没有则 null）、raw（逐字原文片段）、confidence（0-1）。
只切需要行动的事项，信息陈述和已经完成的事项不要切；一句话里有多个独立动作必须拆开；别人的审稿截止不要误判为用户最高优先级。已有课题：{json.dumps(project_names, ensure_ascii=False)}'''
    try:
        content = _request([{"role": "system", "content": system}, {"role": "user", "content": text}], cfg, .15, 15)
        data = _extract_json(content)
        items = data.get("tasks", []) if isinstance(data, dict) else data
        if not isinstance(items, list): raise ValueError("tasks 不是数组")
        for item in items:
            item["board_id"] = {"论文": "paper", "课题": "research", "标书": "grant", "杂事": "misc"}.get(item.get("board"), "misc")
            pname = item.get("project")
            matched = next((p for p in projects if isinstance(p, dict) and pname and p.get("name", "").lower() in pname.lower()), None)
            item["project_id"] = matched.get("id") if matched else item.get("project_id")
            if matched and item.get("workstream"):
                stream = next((w for w in matched.get("workstreams", []) if w.get("name") == item.get("workstream") or item.get("workstream") in w.get("name", "") or w.get("name", "") in item.get("workstream", "")), None)
                if stream: item["workstream_id"] = stream.get("id")
            item["time_state"] = "dated" if item.get("due") else "unknown"
            item["priority"] = clamp_priority(item.get("priority", 3), item.get("due"), item.get("raw", ""))
            item.setdefault("confidence", .72)
        return items, "ai"
    except Exception:
        return parse(text, projects), "offline"


def _local_reply(question: str, tasks: list[dict]) -> str:
    active = [t for t in tasks if t.get("status") not in ("done", "deleted")]
    if not active: return "目前没有未完成任务。你可以告诉我一个想推进的目标，我会帮你拆成下一步。"
    urgent = sorted(active, key=lambda t: (t.get("priority", 4), t.get("due") or "9999"))[:3]
    names = "、".join(t.get("title", "") for t in urgent)
    waiting = sum(1 for t in active if t.get("status") == "waiting")
    if any(k in question for k in ["拆", "分解", "下一步"]):
        return f"可以先把“{urgent[0].get('title','')}”拆成：明确产出物、准备材料、完成第一小步、记录结果。建议先做第一小步，预计 {urgent[0].get('est_hours',1)} 小时。"
    return f"按优先级建议先处理：{names}。先安排 {urgent[0].get('est_hours',1)} 小时专注时间；{('另有 '+str(waiting)+' 件在等别人回复，暂不占用执行清单。') if waiting else '完成后再处理沟通和零碎任务。'}"


def chat_reply(question: str, history: list[dict], tasks: list[dict], config: dict, projects: list[dict] | None = None) -> str:
    cfg = _active_config(config)
    if not cfg.get("api_key"):
        return _local_reply(question, tasks)
    active = [t for t in tasks if t.get("status") not in ("done", "deleted")]
    context = json.dumps([{k: t.get(k) for k in ("title", "board_name", "project_name", "workstream_name", "priority", "due", "time_state", "prerequisite", "est_hours", "status")} for t in active], ensure_ascii=False)
    project_context = json.dumps([{k: p.get(k) for k in ("name", "objective", "current_block", "remaining_hours", "status_counts", "missing_count")} for p in (projects or [])], ensure_ascii=False)
    user_name = config.get("assistant_user_name") or ""
    tone = config.get("assistant_tone") or "温和、直接、像熟悉你的科研同事"
    memory = config.get("assistant_memory") or "暂无额外长期记忆"
    system = f'''你是 SciPlan 中持续工作的科研助理。请用中文回答，像一个认真、熟悉科研节奏的同事。
你能帮助用户规划实验、论文、投稿、文献阅读、时间安排和任务拆解。回答要先直接回答问题，再给出可执行步骤；信息不足时只问最关键的一个澄清问题；不要假装知道不存在的实验结果。
用户称呼：{user_name or '未设置'}。语气偏好：{tone}。用户长期记忆与研究偏好：{memory}
当前任务上下文：{context}
当前课题概览：{project_context}
'''
    messages = [{"role": "system", "content": system}]
    for item in (history or [])[-40:]:
        if item.get("role") in ("user", "assistant") and item.get("content"):
            messages.append({"role": item["role"], "content": item["content"]})
    messages.append({"role": "user", "content": question})
    try:
        return _request(messages, cfg, .35, 45).strip()
    except Exception:
        return "我暂时连接不上当前 AI 服务，但仍可以基于本地任务给建议。" + _local_reply(question, tasks)


def advise(question: str, tasks: list[dict], config: dict):
    return chat_reply(question, [], tasks, config)
