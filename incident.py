import sys
from fractions import Fraction as F
from sequence_lab.grammar.model import Rule, GrammarRevision
from sequence_lab.grammar.revisions import save_grammar
from sequence_lab.delivery.database import open_database
from sequence_lab.cohort.records import SequenceUpdate
from sequence_lab.cohort.revisions import apply_sequences
from sequence_lab.cohort.snapshots import freeze_cohort
from sequence_lab.analysis.execute import analyze_sequence
from sequence_lab.reporting.reports import create_report
from sequence_lab.reporting.read import read_report


def cases():
    yield ("repeated_annotation",
           GrammarRevision("incident-loop", 1, "S", ("S",), ("a",),
                           (Rule("repeat", "S", "unary", ("S",), F(1, 2)),
                            Rule("emit", "S", "emit", ("a",), F(1, 2)))),
           "a", ("repeat",), (F(1),), ((F(2),),))
    yield ("separate_original_ids",
           GrammarRevision("incident-identity", 1, "S", ("S",), ("a",),
                           (Rule("p", "S", "unary", ("S",), F(1, 4)),
                            Rule("q", "S", "unary", ("S",), F(1, 4)),
                            Rule("unused", "S", "unary", ("S",), F(0)),
                            Rule("emit", "S", "emit", ("a",), F(1, 2)))),
           "a", ("p", "unused"), (F(1, 2), F(0)),
           ((F(3, 4), F(0)), (F(0), F(0))))
    yield ("two_child_applications",
           GrammarRevision("incident-children", 1, "S", ("S", "A"), ("a",),
                           (Rule("pair", "S", "binary", ("A", "A"), F(1)),
                            Rule("emit", "A", "emit", ("a",), F(1)))),
           "aa", ("emit",), (F(2),), ((F(0),),))


def main():
    failures = 0
    with open_database() as db:
        for name, grammar, sequence, ids, means, covariance in cases():
            ref = save_grammar(db, grammar)
            apply_sequences(db, [SequenceUpdate(name, 1, sequence)])
            cohort = freeze_cohort(db, [name])
            analysis = analyze_sequence(db, ref, cohort, name, ids)
            report = read_report(db, create_report(db, analysis))
            actual = report.result
            expected = dict(status="ok", evidence=F(1), rule_ids=ids,
                            statistics=dict(means=means, covariance=covariance))
            matched = actual == expected
            failures += not matched
            print(("CASE_OK" if matched else "RULE_COUNT_MISMATCH"), name,
                  "expected=" + repr(expected), "actual=" + repr(actual))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
