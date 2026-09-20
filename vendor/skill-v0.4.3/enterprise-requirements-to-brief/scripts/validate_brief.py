"""Validate the v0.4 contract and derive all confirmation tables from one source."""
import json
import re
import sys
from pathlib import Path

KR23 = ("稳定性", "可迁移性", "安全性", "效率")
BASIS = ("enterprise_rule", "role_common_practice", "verified_standard", "proposal")
OWNERS = ("customer", "customer_optional", "skill_research")
SCOPE_FLAGS = ("complex", "long_chain", "long_cycle", "agent_like", "enterprise_dependency")
RESERVED = {"C-DELIVERY", "C-ADJUST", "C-SAMPLE", "C-FORMAT", "C-REVIEWER", "C-RUBRIC", "C-ISSUE"}


def confirmations(d):
    """Same rows drive local yellow boxes and the section 08 summary; never mutate d."""
    n, m = len(d.get("outputs", [])), len(d.get("kr2_2", []))
    count = sum(x.get("required") is True and x.get("owner") != "skill_research" for x in d.get("inputs", []))
    rows = []
    def add(cid, section, topic, question, answer):
        rows.append(dict(id=cid, section=section, topic=topic, question=question, answer=answer))
    note = d.get("task_fit", {}).get("conversion_note", "").strip()
    if note:
        add("C-ADJUST", "02", "任务调整", note, "□ 确认  □ 调整\n________________")
    sample_question = f"请按上方“企业提供”的{count}项必填内容，提供1至3组示例填写内容。"
    if d.get("sample", {}).get("real"):
        sample_question += "已有真实样例，请核对是否覆盖上述输入；不足时补充。"
    add("C-SAMPLE", "03", "输入样例", sample_question, "示例文件或链接 ________________")
    selected = d.get("selected_output", "")
    options = [f"{'☑' if selected == x.get('id') else '□'} {x.get('label', '')}{'（建议）' if x.get('recommended') else ''}" for x in d.get("output_options", [])]
    options.append("□ 其他 ________")
    add("C-FORMAT", "04", "输出格式", "  ".join(options), "文件保存在哪里或网页放在哪里／谁可以访问 ________________")
    reviewer = d.get("reviewer", {}).get("value", "")
    add("C-REVIEWER", "06", "评分人", "企业负责人或企业指定的评审人", f"{reviewer or '姓名／岗位 ________________'}\n评分日期 ________________")
    add("C-RUBRIC", "07", "评分规则", f"KR1检查{n}项输出，各评完整度、准确度和格式规范；KR2评{m}个维度，KR3评4个维度。均按1至5分评分，各自取平均值。", "是否同意上述评分项目和1至5分标准\n□ 确认  □ 调整 ________________")
    add("C-ISSUE", "07", "当前问题", "公司现在用AI或人工做这项工作时，最常遇到什么问题？", "________________\n________________")
    for row in d.get("confirmations", []):
        if row.get("id") in RESERVED:
            raise ValueError("自定义确认项不能覆盖固定确认项：" + row["id"])
        rows.append({**row, "answer": row.get("answer", "□ 确认  □ 调整\n________________")})
    return sorted(rows, key=lambda x: x["section"])


def validate(d):
    errors = []
    def need(ok, msg):
        if not ok: errors.append(msg)
    def nonempty(v): return isinstance(v, str) and bool(v.strip())
    for key in ("title", "scenario", "purpose", "objective"):
        need(nonempty(d.get(key)), f"{key}不能为空")
    tax = d.get("taxonomy", {})
    for key in ("industry_l1", "industry_l2", "role_l1", "role_l2"):
        need(nonempty(tax.get(key)), f"taxonomy.{key}不能为空")
    need(tax.get("industry_l1") != tax.get("industry_l2"), "大行业和细分行业不能相同")
    need(tax.get("role_l1") != tax.get("role_l2"), "大岗位和细分岗位不能相同")
    for key, limit in (("scenario",130),("purpose",150),("objective",110)):
        need(isinstance(d.get(key),str) and len(d[key]) <= limit, f"{key}过长或类型错误")
    fit = d.get("task_fit", {})
    need(fit.get("skill_task") is True, "必须是Skill任务")
    need(isinstance(fit.get("autonomous_run"),bool), "autonomous_run须如实记录原任务协作方式")
    need(isinstance(fit.get("private_data_required"),bool), "private_data_required须为布尔值")
    need(fit.get("ai_trivial") is False, "任务不能一次通用提示即可完成")
    for key in ("nontrivial_reason", "data_strategy"):
        need(nonempty(fit.get(key)), f"task_fit.{key}不能为空")
    need(isinstance(fit.get("conversion_note"),str), "conversion_note须为字符串")
    for key in ("scope_change_applied", "scope_change_authorized"):
        need(isinstance(fit.get(key, False), bool), f"task_fit.{key}须为布尔值")
    if fit.get("scope_change_applied"):
        need(fit.get("scope_change_authorized") is True, "应用收敛范围前必须获得明确授权")
        need(nonempty(fit.get("conversion_note")), "实际调整范围必须写明任务调整")
        need(fit.get("scope_change_source") in d.get("sources", {}), "范围调整授权必须有来源")
    runtime = d.get("runtime", {})
    need(isinstance(runtime.get("interactive_required"),bool), "interactive_required须为布尔值")
    for key in ("minimum_input", "ambiguity_policy", "human_role_after_run"):
        need(nonempty(runtime.get(key)), f"runtime.{key}不能为空")
    scope = d.get("scope_assessment", {})
    for key in SCOPE_FLAGS:
        need(isinstance(scope.get(key),bool), f"scope_assessment.{key}须为布尔值")
    need(isinstance(scope.get("original_enterprise_dependency", False),bool), "scope_assessment.original_enterprise_dependency须为布尔值")
    scope_triggered = any(scope.get(k) for k in SCOPE_FLAGS) or scope.get("original_enterprise_dependency", False)
    for key in ("note", "student_slice"):
        need(isinstance(scope.get(key),str), f"scope_assessment.{key}须为字符串")
        if scope_triggered:
            need(nonempty(scope.get(key)), f"复杂或依赖任务必须填写scope_assessment.{key}")
    if fit.get("private_data_required"):
        need(scope.get("enterprise_dependency") is True, "私有数据依赖必须明确标记enterprise_dependency")
    sources = d.get("sources", {})
    need(isinstance(sources,dict) and bool(sources), "sources不能为空")
    def source_ok(x): return x in sources or x in ("proposal", "public-practice")
    ids = set()
    def register(x):
        need(nonempty(x) and x not in ids, "ID缺失或重复")
        ids.add(x)
    inputs = d.get("inputs", [])
    need(bool(inputs), "至少有一个输入")
    for item in inputs:
        for key in ("id","owner","name","requirement","example","source"):
            need(nonempty(item.get(key)), f"输入缺少{key}")
        need(item.get("owner") in OWNERS, "输入owner无效")
        need(isinstance(item.get("required"),bool), "required须为布尔值")
        need(source_ok(item.get("source")), f"{item.get('id')}来源不存在")
        register(item.get("id"))
        required = item.get("required") and item.get("owner") != "skill_research"
        if item.get("owner") in ("customer_optional", "skill_research"): need(not item.get("required"), "选填owner不能required")
        need(not(required and item.get("student_fallback")), "必填项不能由学生替代准备")
        for key in ("student_fallback", "dependency_note"):
            need(isinstance(item.get(key,""),str), f"{key}须为字符串")
        if item.get("dependency_note"):
            need(required and item.get("owner") == "customer", "企业依赖项必须是企业必填")
            need(scope.get("enterprise_dependency") is True, "输入依赖必须标记场景enterprise_dependency")
        # Check requests, while permitting explicit prohibitions and enterprise-side login.
        blob = item.get("name", "") + "。" + item.get("requirement", "")
        for sentence in re.split(r"[。；;\n]", blob):
            if re.search(r"密码|Cookie|cookie|验证码|密钥|登录态|访问令牌", sentence):
                need(bool(re.search(r"不提供|不收集|不保存|不含|无需|不要|禁止|不得|不提交", sentence)), "输入不得索取或收集凭据")
    need(any(x.get("required") and x.get("owner") == "customer" for x in inputs), "至少有一个企业必填输入")
    if scope.get("enterprise_dependency"):
        need(any(x.get("dependency_note") and x.get("required") and x.get("owner") == "customer" for x in inputs), "企业依赖任务必须有红字依赖输入")
    outs = d.get("outputs", [])
    need(bool(outs), "outputs不能为空")
    names = set()
    for item in outs:
        for key in ("id","name","detail","example","source"):
            need(nonempty(item.get(key)), f"输出缺少{key}")
        need(item.get("name") not in names, "输出名称重复")
        names.add(item.get("name")); register(item.get("id"))
        need(source_ok(item.get("source")), f"{item.get('id')}输出来源不存在")
    options = d.get("output_options", [])
    need(1 <= len(options) <= 3, "输出格式应有1—3个可行选项")
    need(sum(bool(x.get("recommended")) for x in options) == 1, "只能有一个建议输出格式")
    for x in options:
        for key in ("id","label"):
            need(nonempty(x.get(key)), f"输出格式缺少{key}")
        register(x.get("id"))
    need(not d.get("selected_output") or d["selected_output"] in {x.get("id") for x in options}, "selected_output不存在")
    dims = d.get("kr2_2", [])
    need(bool(dims), "KR2至少一个维度")
    ref_ids = {x.get("id") for x in inputs + outs}
    for x in dims:
        for key in ("id","name","basis","basis_type","company_check","anchor_1","anchor_3","anchor_5"):
            need(nonempty(x.get(key)), f"KR2缺少{key}")
        register(x.get("id"))
        need(x.get("basis_type") in BASIS, "KR2依据类型无效")
        need(x.get("name", "") not in ("完整度","准确度","格式规范","输出准确度","输出完整度"), "KR2不能重复KR1固定维度")
        refs=x.get("refs", [])
        need(bool(refs) and len(refs)==len(set(refs)) and set(refs)<=ref_ids, "KR2引用不存在或重复")
    kr3 = d.get("kr2_3", {})
    need(set(kr3)==set(KR23), "KR3必须且仅含四项固定维度")
    for name, x in kr3.items():
        need(isinstance(x,dict), f"KR3 {name}必须提供检查方法和1、3、5分锚点；旧字符串须先迁移")
        if isinstance(x,dict):
            for key in ("check","anchor_1","anchor_3","anchor_5"):
                need(nonempty(x.get(key)), f"KR3 {name}缺少{key}")
    sample=d.get("sample", {})
    need(type(sample.get("count",3)) is int and 1<=sample.get("count",3)<=3, "sample.count须为1—3")
    need(isinstance(sample.get("real"),bool), "sample.real须为布尔值")
    need(isinstance(sample.get("note"),str), "sample.note须为字符串")
    if sample.get("real"): need(nonempty(sample.get("note")), "真实样例必须注明来源或位置")
    need(isinstance(d.get("rubric_approved"),bool), "rubric_approved须为布尔值")
    for row in d.get("confirmations", []):
        for key in ("id","section","topic","question"):
            need(nonempty(row.get(key)), f"确认项缺少{key}")
        need(row.get("id") not in RESERVED, "自定义确认项不能覆盖固定确认项")
        register(row.get("id"))
        need(row.get("section") in ("01","02","03","04","05","06","07"), "确认项section须为01—07")
        refs=row.get("refs", [])
        need(len(refs)==len(set(refs)) and set(refs)<=ref_ids, "确认项引用不存在或重复")
    return errors


def load_checked(path):
    data=json.loads(Path(path).read_text(encoding="utf-8"))
    errors=validate(data)
    if errors: raise ValueError("\n".join(errors))
    return data

if __name__ == "__main__":
    try:
        data=load_checked(sys.argv[1])
        print(f"通过：{len(data['outputs'])}个KR1组件，{len(data['kr2_2'])}个KR2维度，4个KR3维度。")
    except Exception as exc:
        sys.exit(str(exc))
