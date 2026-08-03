class MarketParticipationIneligible(Exception):
    def __init__(self, result):
        self.result = result
        super().__init__("Market participation is not available.")


class MarketResponsibleParticipationBlocked(Exception):
    def __init__(self, result):
        self.result = result
        super().__init__("Market participation is temporarily unavailable.")
