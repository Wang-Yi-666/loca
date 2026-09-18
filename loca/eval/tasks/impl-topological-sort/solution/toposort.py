"""Topological sorting."""


def toposort(graph):
    """Topologically sort a mapping of {node: [dependencies]}."""
    nodes = set(graph)
    for dependencies in graph.values():
        nodes.update(dependencies)

    pending = {node: set(graph.get(node, [])) for node in nodes}
    result = []
    while pending:
        ready = sorted(node for node, deps in pending.items() if not deps)
        if not ready:
            raise ValueError("graph contains a cycle")
        for node in ready:
            result.append(node)
            del pending[node]
        for deps in pending.values():
            deps.difference_update(ready)
    return result
