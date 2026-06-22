# 导出接口边界与异常编码经验

适用场景：Java/Spring 项目中实现或调整异步导出接口，尤其是“删除筛选入参、保留权限快照/权限模式”的需求。

## 包边界

- `asyncExport.service` 视为通用异步导出基础设施：任务服务、执行器、状态更新、文件存储、Excel writer、MQ sender、handler registry。
- 业务扩展入口是 `asyncExport.handler.<business>`：业务 Handler、业务权限快照构建器、业务导出任务门面等都放这里。
- 不要把待支付订单、账单、会员等具体业务类放到 `asyncExport.service`，否则通用层会被业务侵入。

## 入参边界

- “导出接口不接收筛选条件”不是绝对无参；要区分筛选条件与权限模式。
- 订单号、电话、城市、运营商、时间、售货机列表等属于筛选条件，应从导出创建接口移除。
- 如果现有列表接口的权限计算依赖前端传入的权限模式标识（如 `pointResourceVendorRole`），导出接口可以只保留该参数，权限快照构建时与列表接口保持同一口径。

## 异常编码

- 导出相关异常不要直接 `new VemsException("文案")`。
- 先在 `ErrorConstants` enum 项和内部 `Messages` 常量中定义错误码与文案。
- 使用：
  - `throw new VemsException(ErrorConstants.EXPORT_XXX);`
  - 带 cause 时使用 `new VemsException(ErrorConstants.EXPORT_XXX.getValue(), ErrorConstants.EXPORT_XXX.getMessage(), e)`。
- Controller 接口注释需要列出可能返回的异常编码，至少覆盖创建任务、查询任务、下载任务链路。

## 自检脚本思路

完成后做两个静态检查：

1. 搜索 `asyncExport` 目录下是否还有裸字符串异常：`new VemsException("`。
2. 检查 Controller 导出接口注释是否包含本次新增的 `SP-FRCH-*` 导出错误码。
