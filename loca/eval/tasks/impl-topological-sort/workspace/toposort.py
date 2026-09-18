"""Topological sorting."""


def toposort(graph):
    """Topologically sort a mapping of {node: [dependencies]}.

    - Every node appears after all of its dependencies.
    - Nodes that appear only as dependencies are included in the result.
    - Ties are broken alphabetically, so the output is deterministic.
    - Raise ValueError when the graph contains a cycle (a self-loop counts).
    """
    raise NotImplementedError
