"""Shortest paths over a directed weighted graph."""

import heapq
import math


def shortest_path(edges, start, goal):
    """Dijkstra over the edges given as (source, target, weight) triples."""
    graph = {}
    for source, target, weight in edges:
        graph.setdefault(source, []).append((target, weight))
        graph.setdefault(target, [])

    if start == goal:
        return 0, [start]

    best = {start: 0}
    previous = {}
    queue = [(0, start)]
    while queue:
        cost, node = heapq.heappop(queue)
        if cost > best.get(node, math.inf):
            continue
        for target, weight in graph.get(node, []):
            candidate = cost + weight
            if candidate < best.get(target, math.inf):
                best[target] = candidate
                previous[target] = node
                heapq.heappush(queue, (candidate, target))

    if goal not in best:
        return math.inf, []
    path = [goal]
    while path[-1] != start:
        path.append(previous[path[-1]])
    path.reverse()
    return best[goal], path
