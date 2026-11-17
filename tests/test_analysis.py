from fractions import Fraction as F
from tests.helpers import LabCase, grammar, emit, loop, parallel, branches
from sequence_lab.grammar.model import Rule
from sequence_lab.analysis.execute import analyze_sequence
from sequence_lab.analysis.request import AnalysisRequestError
from sequence_lab.delivery.publish import load_published_analysis
from sequence_lab.compiler.compile import compile_grammar
from sequence_lab.compiler.contributions import select_contributions


class TestAnalysis(LabCase):
    def test_deterministic_emission(self):
        result = self.analyze(grammar([emit()]), "a", ("emit",))
        self.assertEqual(result["evidence"], F(1))
        self.assertEqual(result["statistics"], dict(means=(F(1),), covariance=((F(0),),)))

    def test_unary_geometric_counts(self):
        result = self.analyze(loop(), "a", ("loop",))
        self.assertEqual(result["evidence"], F(1))
        self.assertEqual(result["statistics"]["means"], (F(1),))
        self.assertEqual(result["statistics"]["covariance"], ((F(2),),))

    def test_parallel_rule_identity(self):
        for ids in (("p", "q"), ("q", "p")):
            result = self.analyze(parallel(), "a", ids)
            self.assertEqual(result["rule_ids"], ids)
            self.assertEqual(result["evidence"], F(1))
            self.assertEqual(result["statistics"]["means"], (F(1, 2), F(1, 2)))
            self.assertEqual(result["statistics"]["covariance"],
                             ((F(3, 4), F(1, 4)), (F(1, 4), F(3, 4))))
        plan = compile_grammar(parallel())
        self.assertEqual(len(plan.contributions), 4)
        selected = select_contributions(plan, ("p", "zero"))
        self.assertNotEqual(selected[0].edge_index, selected[1].edge_index)
        zero = self.analyze(parallel(), "a", ("p", "zero"))
        self.assertEqual(zero["statistics"]["means"], (F(1, 2), F(0)))
        self.assertEqual(zero["statistics"]["covariance"],
                         ((F(3, 4), F(0)), (F(0), F(0))))
        original = parallel()
        reversed_grammar = grammar(tuple(reversed(original.rules)), name="reversed")
        self.assertEqual(self.analyze(reversed_grammar, "a", ("q", "p"))["statistics"],
                         result["statistics"])

    def test_exclusive_binary_derivations(self):
        result = self.analyze(branches(), "aa", ("ab", "ba"))
        self.assertEqual(result["evidence"], F(1))
        self.assertEqual(result["statistics"]["means"], (F(1, 2), F(1, 2)))
        self.assertEqual(result["statistics"]["covariance"],
                         ((F(1, 4), F(-1, 4)), (F(-1, 4), F(1, 4))))

    def test_impossible_sequence(self):
        value = grammar([emit()])
        self.analyze(value, "a", ("emit",))
        impossible = self.analyze(value, "b", ("emit",))
        self.assertEqual(impossible, dict(status="impossible", evidence=F(0),
                                         rule_ids=("emit",), statistics=None))
        zero_request = self.analyze(value, "b", ())
        self.assertIsNone(zero_request["statistics"])

    def test_request_contract(self):
        binding = self.prepare(parallel())
        for ids in ((), ("q",), ("zero", "p")):
            aid = analyze_sequence(self.db, *binding, ids)
            result = load_published_analysis(self.db, aid)["result"]
            self.assertEqual(result["rule_ids"], ids)
            self.assertEqual(len(result["statistics"]["means"]), len(ids))
        before = self.db.connection.execute("SELECT count(*) FROM analyses").fetchone()[0]
        bad = [(*binding, ("p", "p")), (*binding, ("p", "q", "zero")),
               (*binding, ("absent",)), (999, binding[1], binding[2], ()),
               (binding[0], 999, binding[2], ()),
               (binding[0], binding[1], "outsider", ())]
        for args in bad:
            with self.assertRaises(AnalysisRequestError):
                analyze_sequence(self.db, *args)
        self.assertEqual(before, self.db.connection.execute(
            "SELECT count(*) FROM analyses").fetchone()[0])

    def test_ordered_spans_and_unicode(self):
        value = grammar([Rule("join", "S", "binary", ("A", "B"), F(1)),
                         emit("a", "A", "é"), emit("b", "B", "🙂")],
                        nts=("S", "A", "B"), alphabet=("é", "🙂"))
        self.assertEqual(self.analyze(value, "é🙂", ())["evidence"], F(1))
        self.assertEqual(self.analyze(value, "🙂é", ())["evidence"], F(0))
        ascii_value = grammar([Rule("join", "S", "binary", ("A", "B"), F(1)),
                               emit("a", "A"), emit("b", "B", "b")],
                              nts=("S", "A", "B"), name="ascii")
        self.assertEqual(self.analyze(ascii_value, "ab", ())["evidence"], F(1))
        self.assertEqual(self.analyze(ascii_value, "ba", ())["evidence"], F(0))
        self.assertEqual(self.analyze(grammar([emit(char="\ud800")], alphabet=("\ud800",),
                                               name="surrogate"), "\ud800", ())["evidence"], F(1))
        self.assertEqual(self.analyze(grammar([emit(char="é")], alphabet=("é",),
                                               name="unicode"), "e\u0301", ())["evidence"], F(0))

    def test_weight_sweep(self):
        for i, q in enumerate((F(0), F(1, 3), F(1, 2), F(19, 20))):
            result = self.analyze(loop(q, name="sweep" + str(i)), "a", ("loop",))
            self.assertEqual(result["evidence"], F(1))
            self.assertEqual(result["statistics"]["means"], (q / (1-q),))
            self.assertEqual(result["statistics"]["covariance"], ((q / (1-q)**2,),))

    def test_binary_branch_products(self):
        value = grammar([Rule("join", "S", "binary", ("A", "A"), F(1)),
                         emit("a", "A")], nts=("S", "A"))
        result = self.analyze(value, "aa", ("a", "join"))
        self.assertEqual(result["statistics"]["means"], (F(2), F(1)))
        self.assertEqual(result["statistics"]["covariance"],
                         ((F(0), F(0)), (F(0), F(0))))
        self.assertEqual(result["statistics"]["covariance"][0][0] +
                         result["statistics"]["means"][0]**2, F(4))

    def test_recursive_binary_with_loops(self):
        value = grammar([Rule("loop", "S", "unary", ("S",), F(2, 5)),
                         Rule("fork", "S", "binary", ("S", "S"), F(1, 5)),
                         emit(weight=F(2, 5))])
        result = self.analyze(value, "aaa", ("loop", "fork"))
        # Two ordered full binary trees, five nodes; geometric repeats per node.
        self.assertEqual(result["evidence"], F(16, 243))
        self.assertEqual(result["statistics"]["means"], (F(10, 3), F(2)))
        self.assertEqual(result["statistics"]["covariance"],
                         ((F(50, 9), F(0)), (F(0), F(0))))

    def test_mutual_unary_cycle(self):
        value = grammar([Rule("ab", "A", "unary", ("B",), F(1, 2)),
                         emit("a", "A", weight=F(1, 2)),
                         Rule("ba", "B", "unary", ("A",), F(1, 2)),
                         emit("b", "B", "b", F(1, 2))],
                        nts=("A", "B"), start="A")
        result = self.analyze(value, "a", ("ab", "ba"))
        self.assertEqual(result["evidence"], F(2, 3))
        self.assertEqual(result["statistics"]["means"], (F(1, 3), F(1, 3)))
        self.assertEqual(result["statistics"]["covariance"],
                         ((F(4, 9), F(4, 9)), (F(4, 9), F(4, 9))))

    def test_same_form_contributions_keep_distinct_positions(self):
        same_form = grammar([Rule("p", "S", "unary", ("S",), F(1, 4)),
                             Rule("q", "S", "unary", ("S",), F(1, 4)),
                             emit(weight=F(1, 2))], name="unary-shape")
        plan = compile_grammar(same_form)
        positions = {c.rule_id: (c.kind, c.edge_index) for c in plan.contributions}
        self.assertEqual(len(set(positions.values())), len(positions))
        for contribution in plan.contributions:
            edges = {"emit": plan.emissions, "unary": plan.unary,
                     "binary": plan.binary}[contribution.kind]
            self.assertEqual(edges[contribution.edge_index].rule_id,
                             contribution.rule_id)
        binary_same_form = grammar(
            [Rule("x", "S", "binary", ("S", "S"), F(1, 4)),
             Rule("y", "S", "binary", ("S", "S"), F(1, 4)),
             emit(weight=F(1, 2))], name="binary-shape")
        plan = compile_grammar(binary_same_form)
        positions = {c.rule_id: (c.kind, c.edge_index) for c in plan.contributions}
        self.assertEqual(len(set(positions.values())), len(positions))
        result = self.analyze(binary_same_form, "aa", ("x", "y"))
        # Both same-form binary rules compete for the single split of "aa":
        # exactly one of them applies in every parse, so the joint count is
        # always 1 and the two indicators are perfectly anti-correlated.
        self.assertEqual(result["evidence"], F(1, 8))
        self.assertEqual(result["statistics"]["means"], (F(1, 2), F(1, 2)))
        self.assertEqual(result["statistics"]["covariance"],
                         ((F(1, 4), F(-1, 4)), (F(-1, 4), F(1, 4))))

    def test_each_application_counted_individually(self):
        value = grammar([Rule("pair", "S", "binary", ("A", "A"), F(1)),
                         emit("emit", "A")], nts=("S", "A"), name="two-children")
        result = self.analyze(value, "aa", ("emit",))
        self.assertEqual(result["evidence"], F(1))
        self.assertEqual(result["statistics"]["means"], (F(2),))
        self.assertEqual(result["statistics"]["covariance"], ((F(0),),))

    def test_recursive_binary_with_loops_all_splits(self):
        value = grammar([Rule("loop", "S", "unary", ("S",), F(1, 5)),
                         Rule("fork", "S", "binary", ("S", "S"), F(1, 5)),
                         emit(weight=F(3, 5))], name="recursive-both")
        result = self.analyze(value, "aaa", ("loop", "fork"))
        self.assertEqual(result["evidence"], F(27, 512))
        self.assertEqual(result["statistics"]["means"], (F(5, 4), F(2)))
        self.assertEqual(result["statistics"]["covariance"],
                         ((F(25, 16), F(0)), (F(0), F(0))))

    def test_zero_weight_same_form_rule_reports_exact_zero(self):
        value = grammar([Rule("live", "S", "unary", ("S",), F(1, 2)),
                         Rule("idle", "S", "unary", ("S",), F(0)),
                         emit(weight=F(1, 2))], name="idle")
        plan = compile_grammar(value)
        live, idle = select_contributions(plan, ("live", "idle"))
        self.assertNotEqual((live.kind, live.edge_index), (idle.kind, idle.edge_index))
        result = self.analyze(value, "a", ("live", "idle"))
        self.assertEqual(result["evidence"], F(1))
        self.assertEqual(result["statistics"]["means"], (F(1), F(0)))
        self.assertEqual(result["statistics"]["covariance"],
                         ((F(2), F(0)), (F(0), F(0))))
        reversed_grammar = grammar(tuple(reversed(value.rules)), name="idle-reversed")
        self.assertEqual(self.analyze(reversed_grammar, "a", ("live", "idle"))["statistics"],
                         result["statistics"])
