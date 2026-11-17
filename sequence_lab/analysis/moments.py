from dataclasses import dataclass, replace
from fractions import Fraction
from types import MappingProxyType
from sequence_lab.compiler.contributions import select_contributions
from sequence_lab.compiler.unary import build_unary_matrix, build_unary_closure
from sequence_lab.analysis.evidence import compute_evidence


@dataclass(frozen=True)
class ConditionalStatistics:
    means: tuple[Fraction, ...]
    covariance: tuple[tuple[Fraction, ...], ...]

    def canonical_record(self):
        return dict(means=self.means, covariance=self.covariance)


@dataclass(frozen=True)
class AnalysisResult:
    status: str
    evidence: Fraction
    rule_ids: tuple[str, ...]
    statistics: ConditionalStatistics | None

    def canonical_record(self):
        return dict(status=self.status, evidence=self.evidence, rule_ids=self.rule_ids,
                    statistics=None if self.statistics is None else
                    self.statistics.canonical_record())

    @classmethod
    def from_record(cls, record):
        if type(record) is not dict or set(record) != {
                "status", "evidence", "rule_ids", "statistics"}:
            raise ValueError("invalid result structure")
        stats = record["statistics"]
        if stats is not None:
            if type(stats) is not dict or set(stats) != {"means", "covariance"}:
                raise ValueError("invalid statistics structure")
            stats = ConditionalStatistics(**stats)
        result = cls(record["status"], record["evidence"], record["rule_ids"], stats)
        result.validate()
        return result

    def validate(self):
        if not isinstance(self.evidence, Fraction) or not 0 <= self.evidence <= 1:
            raise ValueError("invalid evidence")
        if (type(self.rule_ids) is not tuple or len(self.rule_ids) > 2
                or any(type(x) is not str or not x for x in self.rule_ids)
                or len(set(self.rule_ids)) != len(self.rule_ids)):
            raise ValueError("invalid result rule identities")
        if self.evidence == 0:
            if self.status != "impossible" or self.statistics is not None:
                raise ValueError("zero evidence must have no conditional statistics")
            return
        if self.status != "ok" or not isinstance(self.statistics, ConditionalStatistics):
            raise ValueError("positive evidence requires statistics")
        means, covariance = self.statistics.means, self.statistics.covariance
        d = len(self.rule_ids)
        if (type(means) is not tuple or type(covariance) is not tuple
                or len(means) != d or len(covariance) != d
                or any(type(row) is not tuple or len(row) != d for row in covariance)):
            raise ValueError("invalid statistics dimensions")
        if any(not isinstance(x, Fraction) or x < 0 for x in means):
            raise ValueError("invalid means")
        if any(not isinstance(x, Fraction) for row in covariance for x in row):
            raise ValueError("statistics must be exact Fraction")
        for r in range(d):
            if covariance[r][r] < 0:
                raise ValueError("negative variance")
            for s in range(d):
                if covariance[r][s] != covariance[s][r]:
                    raise ValueError("asymmetric covariance")


@dataclass(frozen=True)
class MomentChart:
    evidence: object
    rule_ids: tuple[str, ...]
    first: object
    second: object


def compute_moments(plan, evidence, rule_ids):
    if evidence.plan is not plan:
        raise ValueError("moment/evidence plan mismatch")
    selected = select_contributions(plan, rule_ids)
    d, n = len(selected), len(plan.symbols)

    def excluded_chart(selection):
        removed = {(selected[r].kind, selected[r].edge_index) for r in selection}
        groups = {}
        for kind, edges, field in (("emit", plan.emissions, "emissions"),
                                   ("unary", plan.unary, "unary"),
                                   ("binary", plan.binary, "binary")):
            groups[field] = tuple(edge for i, edge in enumerate(edges)
                                  if (kind, i) not in removed)
        matrix = build_unary_matrix(plan.symbols, groups["unary"])
        reduced = replace(plan, **groups, unary_matrix=matrix,
                          closure=build_unary_closure(matrix))
        return compute_evidence(reduced, evidence.sequence)

    absent = tuple(excluded_chart((r,)) for r in range(d))
    joint_absent = {(r, s): excluded_chart((r, s))
                    for r in range(d) for s in range(r + 1, d)}
    first, second = {}, {}
    for span, z in evidence.values.items():
        first[span] = tuple(tuple(z[a] - absent[r].values[span][a] for a in range(n))
                            for r in range(d))
        rows = []
        for r in range(d):
            row = []
            for s in range(d):
                if r == s:
                    row.append(first[span][r])
                else:
                    both = joint_absent[min(r, s), max(r, s)].values[span]
                    row.append(tuple(z[a] - absent[r].values[span][a]
                                     - absent[s].values[span][a] + both[a]
                                     for a in range(n)))
            rows.append(tuple(row))
        second[span] = tuple(rows)
    return MomentChart(evidence, tuple(rule_ids), MappingProxyType(first),
                       MappingProxyType(second))


def condition_statistics(moments):
    chart = moments.evidence
    z = chart.start_evidence
    if z == 0:
        result = AnalysisResult("impossible", z, moments.rule_ids, None)
    else:
        span = (0, len(chart.sequence))
        start = chart.plan.start_index
        means = tuple(row[start] / z for row in moments.first[span])
        covariance = tuple(tuple(moments.second[span][r][s][start] / z - means[r] * means[s]
                                 for s in range(len(means))) for r in range(len(means)))
        result = AnalysisResult("ok", z, moments.rule_ids,
                                ConditionalStatistics(means, covariance))
    result.validate()
    return result
