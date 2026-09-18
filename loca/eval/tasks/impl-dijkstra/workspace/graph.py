"""Shortest paths over a directed weighted graph."""


def shortest_path(edges, start, goal):
    """Dijkstra over the edges given as (source, target, weight) triples.

    Weights are positive. Return (total_cost, [nodes]) for the cheapest route
    from `start` to `goal`. When `goal` is unreachable return (math.inf, []).
    When `start` equals `goal` return (0, [start]).
    """
    raise NotImplementedError
