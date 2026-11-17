# 规则次数质控事故

同一固定序列的解释概率看起来正常，但递归注释使用量偏低，未使用的原始规则也出现在质控统计中。本题只修复既有分析链；接口、输入支持、冻结、事务、报告和导出沿用 README.md。

## 可复算输入与结果

incident.py 使用公开业务接口登记以下三个独立语法、冻结来源并读取真实报告，权重均为 Fraction：

* repeated_annotation：S→S 的 repeat 权重 1/2，S→a 的 emit 权重 1/2。序列 a，请求 repeat；证据 1，均值 (1,)，协方差 ((2,),)。
* separate_original_ids：S→S 的 p、q、unused 权重分别为 1/4、1/4、0，S→a 的 emit 权重 1/2。序列 a，请求 (p, unused)；证据 1，均值 (1/2, 0)，协方差 ((3/4, 0), (0, 0))。请求 (p, q) 时应为均值 (1/2, 1/2)，协方差 ((3/4, 1/4), (1/4, 3/4))。
* two_child_applications：S→AA 的 pair 权重 1，A→a 的 emit 权重 1。序列 aa，请求 emit；证据 1，均值 (2,)，协方差 ((0,),)。

全部有限有序解析均参与条件化。不同原始规则 ID 分别计数，同形与零权重规则也保留身份；一次解析中的多次应用不能合并。所有结果必须是精确 Fraction，不采用浮点容差。其余边界及手算关系见 README.md。

## 保留的库接口约定

除 README.md 的端到端接口外，现有 compile_grammar(grammar) 返回 CompiledPlan；select_contributions(plan, rule_ids) 按请求顺序返回原始规则贡献。两函数分别由 sequence_lab.compiler.compile 与 sequence_lab.compiler.contributions 导入。

贡献目录须完整覆盖原始规则；每项的 rule_id、kind、edge_index 对应该规则自身的执行边，ID、种类、权重及左右部一致。不同原始规则不能共用同一个执行位置，零权重规则也须保留。执行边顺序不固定，但返回的位置必须正确引用本计划的边。该约定已有原测试，不因本次修复改变。

## 运行与交付

在项目根目录执行 python3.11 -B incident.py。脚本逐项打印 expected 和 actual；任一业务结果不符时输出 RULE_COUNT_MISMATCH 并退出 1，全部相符时输出 CASE_OK 并退出 0。

README.md 中的 verify.py、demo.py 和 .pointwise-runtime.json 保持原用途。verify 必须保留并运行全部原断言；故障基线中相关断言的失败不应被删除或改成接受错误数值。修复后原完整回归及事故入口均应通过，demo 应展示真实修复结果。补充必要回归及简短根因、交接不变量和实际验证说明。
