"""Reference natural-language normalizer used by offline routing evals.

Production adapters may use a model to produce RouteIntent.  This small,
deterministic normalizer is deliberately kept out of the core router and acts
as a regression baseline for the bilingual fixture corpus.
"""

from __future__ import annotations

import re

from .model import RouteIntent


SIGNATURES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("explain", (r"只解释", r"解释.*(?:skill|流程|能力)", r"介绍.*(?:skill|流程|能力)", r"不执行", r"explain.*(?:skill|flow|capability)", r"what .* does", r"how .* works", r"do not execute")),
    ("release", (r"发布", r"上线", r"回滚", r"灰度", r"rollout", r"release", r"deploy to production", r"production deployment")),
    ("diagnose", (r"定位.*(?:bug|故障|问题)", r"排查", r"性能.*(?:回退|下降|变慢)", r"debug", r"diagnos", r"root cause", r"performance regression")),
    ("review", (r"代码评审", r"设计评审", r"自动评审", r"阶段.*(?:审计|评审|门禁|blocker)", r"评审.*(?:diff|分支|方案|代码)", r"stage.*(?:audit|review|gate|blocker)", r"review.*(?:diff|branch|pull request|design|code)", r"\bpr\b")),
    ("evolve", (r"改进.*(?:skill|agent|流程)", r"(?:skill|agent).*改进", r"演进.*(?:skill|agent)", r"复盘.*(?:skill|agent|助手)", r"evolve.*(?:skill|agent)", r"improve.*(?:skill|agent)", r"retrospective.*assistant")),
    ("wayfind", (r"长期任务", r"多会话", r"路线图", r"当前前沿", r"multi-session", r"long-running", r"wayfind", r"current frontier", r"roadmap", r"evidence frontier")),
    ("research", (r"调研", r"研究.*(?:开源|项目|技术|标准)", r"官方文档", r"research", r"compare.*(?:library|project|standard)", r"primary sources")),
    ("model", (r"领域模型", r"统一术语", r"业务术语", r"术语.*歧义", r"ubiquitous language", r"domain model", r"domain terminology", r"model the")),
    ("prototype", (r"原型", r"交互方案.*对比", r"throwaway", r"prototype", r"interaction variants", r"state explorer")),
    ("shape", (r"需求准入", r"需求澄清", r"澄清.*需求", r"验收标准", r"明确.*(?:范围|非目标)", r"shape.*(?:request|feature)", r"acceptance criteria", r"clarify.*requirement")),
    ("decide", (r"需要我决定", r"待决策", r"帮我.*(?:选择|做决定)", r"decision interview", r"trade-off.*(?:choose|decide)", r"which decision", r"help me choose")),
    ("context", (r"梳理.*(?:仓库|代码|调用链|影响范围)", r"代码上下文", r"调用链", r"影响范围", r"map.*repository", r"trace.*call", r"impact scope", r"repository context")),
    ("design", (r"概要设计", r"详细设计", r"架构方案", r"接口设计", r"设计.*(?:模块|系统|改造)", r"architecture design", r"detailed design", r"design.*(?:module|system|refactor|interface)")),
    ("implement", (r"实现.*(?:功能|需求|接口|页面|修复)", r"开发.*(?:功能|需求|页面)", r"修改代码", r"写代码", r"implement", r"build.*(?:feature|page|endpoint)", r"change the code", r"add.*(?:feature|endpoint)")),
)

RISK_PATTERNS = {
    "production": (r"生产", r"线上", r"production"),
    "destructive": (r"删除历史", r"清空", r"不可逆", r"drop table", r"delete history", r"irreversible"),
    "history-rewrite": (r"reset --hard", r"force push", r"改写历史"),
    "credential": (r"凭证", r"密钥", r"credential", r"secret"),
    "security": (r"安全策略", r"权限策略", r"security policy"),
    "cross-repository": (r"另一个仓库", r"跨仓库", r"another repository", r"cross-repository"),
}

ACTION_PATTERNS = {
    "push": (r"推送", r"\bpush\b"),
    "commit": (r"提交代码", r"创建提交", r"\bcommit\b"),
    "publish": (r"发布插件", r"发布包", r"\bpublish\b"),
    "external-message": (r"发送邮件", r"发消息", r"send (?:an )?(?:email|message)"),
}


def normalize_request(request: str) -> RouteIntent:
    text = request.strip().lower()
    matches = [kind for kind, patterns in SIGNATURES if any(re.search(pattern, text) for pattern in patterns)]
    kind = matches[0] if matches else "context"
    confidence = 0.92 if len(matches) == 1 else (0.82 if len(matches) > 1 else 0.35)
    risks = [risk for risk, patterns in RISK_PATTERNS.items() if any(re.search(pattern, text) for pattern in patterns)]
    actions = [action for action, patterns in ACTION_PATTERNS.items() if any(re.search(pattern, text) for pattern in patterns)]
    return RouteIntent(
        task_kind=kind,
        requested_outcome=request.strip(),
        scope=[],
        risk_signals=risks,
        requested_external_actions=actions,
        confidence=confidence,
        evidence=["自然语言请求由确定性 eval adapter 规范化"],
    )
