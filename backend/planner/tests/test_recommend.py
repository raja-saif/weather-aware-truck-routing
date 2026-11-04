from planner.domain.recommend import RouteScore, rank, recommend
from planner.domain.risk import RiskLevel as R

HOUR = 3600


def score(rid, *, nt=0, severe=0, high=0, avg=0.0, hours=10.0):
    return RouteScore(
        route_id=rid,
        name=f"Route {rid}",
        miles_by_level={R.NO_TRAVEL: nt, R.SEVERE: severe, R.HIGH: high},
        avg_risk=avg,
        trip_s=hours * HOUR,
    )


def ids(scores):
    return [s.route_id for s in rank(scores)]


def test_fewest_severe_miles_wins_even_if_slower():
    assert ids([score("A", severe=20, hours=10), score("B", severe=0, high=300, hours=14)]) == ["B", "A"]


def test_high_miles_break_severe_ties():
    assert ids([score("A", severe=10, high=50), score("B", severe=10, high=20)]) == ["B", "A"]


def test_average_risk_breaks_mile_ties():
    assert ids([score("A", avg=0.6), score("B", avg=0.3)]) == ["B", "A"]


def test_travel_time_breaks_full_ties():
    assert ids([score("A", hours=12), score("B", hours=11)]) == ["B", "A"]


def test_near_equal_average_risk_lets_travel_time_decide():
    assert ids([score("A", avg=0.10, hours=12), score("B", avg=0.13, hours=11)]) == ["B", "A"]


def test_no_travel_miles_rank_before_severe_miles():
    # 10 No Travel miles are worse than 15 Severe miles
    assert ids([score("A", nt=10), score("B", severe=15)]) == ["B", "A"]


def test_sub_half_mile_differences_are_ignored():
    assert ids([score("A", severe=10.2, hours=9), score("B", severe=10.0, hours=10)]) == ["A", "B"]


def test_recommend_explains_and_warns():
    result = recommend([score("A", severe=40, hours=9), score("B", severe=0, high=5, hours=10), score("C", nt=3)])
    assert result["route_id"] == "B"
    assert result["ranking"] == ["B", "A", "C"]
    by_route = {c["route_id"]: c for c in result["comparisons"]}
    assert by_route["A"]["decided_by"] == "severe_miles"
    assert by_route["C"]["decided_by"] == "no_travel_miles"
    assert "0 Severe miles vs 40" in by_route["A"]["reason"]
    assert result["warnings"] == []


def test_recommend_warns_when_no_route_is_passable():
    result = recommend([score("A", nt=5), score("B", nt=8)])
    assert result["route_id"] == "A"
    assert "No Travel" in result["warnings"][0]


def test_explain_time_difference():
    result = recommend([score("A", hours=11.5), score("B", hours=10)])
    assert result["comparisons"][0]["reason"] == (
        "Same Severe and High exposure as Route A and similar average risk (0.00 vs 0.00), but 1 h 30 min faster."
    )
