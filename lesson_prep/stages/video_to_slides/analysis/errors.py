class AnalysisError(RuntimeError):
    """A recoverable or fatal analysis problem shown to the user."""


class AnalysisCancelled(RuntimeError):
    """Raised when the user cancels an analysis task."""

