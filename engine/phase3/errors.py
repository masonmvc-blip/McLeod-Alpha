from __future__ import annotations


class Phase3Error(ValueError):
    pass


class ResearchContextError(Phase3Error):
    pass


class Phase3ApprovalError(Phase3Error):
    pass


class Phase3EIPVError(Phase3Error):
    pass
