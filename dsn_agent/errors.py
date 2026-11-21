class AnalysisError(Exception):
    def __init__(self, message: str, code: str = "analysis_failed", status: int = 422):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status
