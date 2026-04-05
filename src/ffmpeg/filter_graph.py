"""Filter-graph file I/O operations.

This module contains the file-writing operation that cannot be part of the pure
sr_filter_graph package. All pure filter graph building logic has been moved
to packages/sr_filter_graph/.
"""

from pathlib import Path


def write_filter_graph_script(path: Path, filter_graph: str) -> Path:
    """Write filter graph text to a file and return the path.
    
    This is the only impure operation in the filter graph workflow.
    All graph building logic is pure and lives in sr_filter_graph.
    
    Args:
        path: Path to write the filter graph script
        filter_graph: The filter graph string to write
        
    Returns:
        The path that was written to
    """
    path.write_text(filter_graph, encoding="utf-8")
    return path
