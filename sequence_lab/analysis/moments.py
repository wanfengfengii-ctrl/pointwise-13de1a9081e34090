from dataclasses import dataclass
from fractions import Fraction
from types import MappingProxyType
from sequence_lab.compiler.contributions import select_contributions


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


class _Ring:
    """Truncated multivariate power series in marker increments, total degree <= 2.

    Marker x_r for a selected rule is represented as 1 + delta_r.  A ring value
    keeps only terms needed for the constant, first and raw second moments.
    """

    def __init__(self, dimension):
        self.dimension = dimension
        self.zero_exponent = (0,) * dimension

    def one(self):
        return {self.zero_exponent: Fraction(1)}

    def variable(self, index):
        exponent = [0] * self.dimension
        exponent[index] = 1
        return {tuple(exponent): Fraction(1)}

    def add(self, left, right):
        result = dict(left)
        for exponent, coefficient in right.items():
            total = result.get(exponent, Fraction(0)) + coefficient
            if total:
                result[exponent] = total
            else:
                result.pop(exponent, None)
        return result

    def scale(self, value, factor):
        factor = Fraction(factor)
        if not factor:
            return {}
        return {exponent: coefficient * factor
                for exponent, coefficient in value.items() if coefficient * factor}

    def sub(self, left, right):
        return self.add(left, self.scale(right, -1))

    def multiply(self, left, right):
        result = {}
        for left_exponent, left_coefficient in left.items():
            for right_exponent, right_coefficient in right.items():
                exponent = tuple(a + b for a, b in zip(left_exponent, right_exponent))
                if sum(exponent) > 2:
                    continue
                total = (result.get(exponent, Fraction(0))
                         + left_coefficient * right_coefficient)
                if total:
                    result[exponent] = total
                else:
                    result.pop(exponent, None)
        return result

    def inverse(self, value):
        pivot = value.get(self.zero_exponent, Fraction(0))
        if pivot == 0:
            raise ValueError("non-invertible marker value")
        quotient = self.scale(value, 1 / pivot)
        quotient[self.zero_exponent] = Fraction(0)
        squared = self.multiply(quotient, quotient)
        series = self.add(self.one(), self.sub(squared, quotient))
        return self.scale(series, 1 / pivot)

    def matrix_inverse(self, matrix):
        size = len(matrix)
        if any(len(row) != size for row in matrix):
            raise ValueError("linear system dimensions disagree")
        augmented = [[dict(value) for value in row]
                     + [self.one() if i == j else {} for j in range(size)]
                     for i, row in enumerate(matrix)]
        for column in range(size):
            pivot = next((i for i in range(column, size)
                          if augmented[i][column].get(self.zero_exponent, 0)), None)
            if pivot is None:
                raise ValueError("singular marker system")
            augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
            scale = self.inverse(augmented[column][column])
            augmented[column] = [self.multiply(scale, value) for value in augmented[column]]
            for row in range(size):
                if row == column:
                    continue
                factor = augmented[row][column]
                if not factor:
                    continue
                augmented[row] = [self.sub(value, self.multiply(factor, pivot_value))
                                  for value, pivot_value in
                                  zip(augmented[row], augmented[column])]
        return tuple(tuple(row[size:]) for row in augmented)


def _marked_chart(plan, sequence, selected):
    ring = _Ring(len(selected))
    marker_index = {contribution.rule_id: index
                    for index, contribution in enumerate(selected)}

    def marker(rule_id):
        if rule_id not in marker_index:
            return ring.one()
        return ring.add(ring.one(), ring.variable(marker_index[rule_id]))

    n = len(plan.symbols)
    unary_matrix = [[{} for _ in range(n)] for _ in range(n)]
    for edge in plan.unary:
        contribution = ring.scale(marker(edge.rule_id), edge.weight)
        unary_matrix[edge.lhs][edge.child] = ring.add(
            unary_matrix[edge.lhs][edge.child], contribution)
    system = [[ring.sub(ring.one() if i == j else {}, unary_matrix[i][j])
               for j in range(n)] for i in range(n)]
    closure = ring.matrix_inverse(system)

    def apply(values):
        return tuple(
            _ring_sum(ring, (ring.multiply(closure[i][j], values[j]) for j in range(n)))
            for i in range(n))

    chart = {}
    for length in range(1, len(sequence) + 1):
        for i in range(len(sequence) - length + 1):
            j = i + length
            base = [{} for _ in range(n)]
            if length == 1:
                for edge in plan.emissions:
                    if edge.character == sequence[i]:
                        base[edge.lhs] = ring.add(
                            base[edge.lhs], ring.scale(marker(edge.rule_id), edge.weight))
            for edge in plan.binary:
                edge_marker = ring.scale(marker(edge.rule_id), edge.weight)
                for k in range(i + 1, j):
                    product = ring.multiply(
                        ring.multiply(edge_marker, chart[i, k][edge.left]),
                        chart[k, j][edge.right])
                    base[edge.lhs] = ring.add(base[edge.lhs], product)
            chart[i, j] = apply(base)
    return chart


def _ring_sum(ring, values):
    total = {}
    for value in values:
        total = ring.add(total, value)
    return total


def compute_moments(plan, evidence, rule_ids):
    if evidence.plan is not plan:
        raise ValueError("moment/evidence plan mismatch")
    selected = select_contributions(plan, rule_ids)
    d, n = len(selected), len(plan.symbols)
    ring = _Ring(d)
    chart = _marked_chart(plan, evidence.sequence, selected)
    marked_evidence = chart[(0, len(evidence.sequence))][plan.start_index].get(
        ring.zero_exponent, Fraction(0))
    if marked_evidence != evidence.start_evidence:
        raise ValueError("moment/evidence chart divergence")

    first, second = {}, {}
    for span, values in chart.items():
        first[span] = tuple(
            tuple(values[a].get(_unit(ring, r), Fraction(0)) for a in range(n))
            for r in range(d))
        rows = []
        for r in range(d):
            row = []
            for s in range(d):
                if r == s:
                    # Coefficient of delta_r^2 counts unordered pairs of
                    # applications, so E[n_r^2] = E[n_r(n_r-1)] + E[n_r].
                    exponent = tuple(2 * value for value in _unit(ring, r))
                else:
                    exponent = tuple(a + b for a, b in
                                     zip(_unit(ring, r), _unit(ring, s)))
                raw = [values[a].get(exponent, Fraction(0)) for a in range(n)]
                if r == s:
                    raw = [2 * raw[a] + first[span][r][a] for a in range(n)]
                row.append(tuple(raw))
            rows.append(tuple(row))
        second[span] = tuple(rows)
    return MomentChart(evidence, tuple(rule_ids), MappingProxyType(first),
                       MappingProxyType(second))


def _unit(ring, index):
    exponent = [0] * ring.dimension
    exponent[index] = 1
    return tuple(exponent)


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
