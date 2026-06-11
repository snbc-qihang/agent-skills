# Plugin feedback -> generic rules/regression workflow

Use this reference when the user gives concrete business-design corrections for the `agent-skills` / `teamwork-engineering-assistant` plugin and asks to improve the plugin.

## Durable pattern
1. Do not immediately code when the user explicitly says the plan must be approved before implementation (e.g. “方案没有问题后再落代码”). First produce an optimization plan.
2. Split the input into two buckets:
   - Generic team-engineering rules that belong in generator source, SKILL.md, validators, workflow, or rule catalog.
   - Concrete requirement facts that belong only in eval/regression fixtures or references, not in general-purpose rules.
3. Call out rule conflicts explicitly instead of silently weakening gates. Example: if the team default requires an MQ dead-letter queue but the concrete case says “无死信队列”, keep the default rule and model the case as an explicit constraint/waiver requiring compensating controls such as retry, backlog alerting, failure logs, manual handling, and review status.
4. For DB/MQ/Redis/interface/exception feedback, prefer capability-level improvements:
   - MQ: distinguish exchange, routingKey, queue, and business message key/configType; different message keys usually require separate consumers/handlers even on the same queue/routingKey.
   - Redis: distinguish idempotency records from short-lived out-of-order protection records; Redis remains a short-state/coordination layer, not a fact source.
   - DB: derive indexes from query patterns, sort order, permission filters, data volume, and sensitivity; ask only for missing facts that cannot be inferred.
   - Interfaces: generate only APIs owned by the current service; external-service detail APIs should be listed as dependencies, not local API contracts.
   - Exceptions: enforce system-service-module-code structure and numeric error ranges from the project profile.
5. After the plan is accepted, modify the generator first, regenerate assets, then add deterministic regression tests that verify behavior rather than text presence.

## Pitfall
Do not hard-code a single requirement’s queue names, message keys, Redis keys, service names, software demand numbers, or designer names into reusable rule text. Put those details in eval cases or references only.
